#!/usr/bin/env python3
"""Custom feature benchmark for Prompt Tokenizer Prefix Caching (v0.1.45 Component 4 / PR #567 / #1852).

Empirically compares Full Tokenization (re-encoding entire conversation from turn 0)
against Prefix Tokenization (PromptEncoder resuming from the last shared special token boundary).
Tests exact token ID bitwise parity and CPU encoding latency across expanding multi-turn agent sessions
up to ~32K context depth on the real Qwen3.8-Flash-Next Coder vocabulary.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))
import strata_tokenizer as ST
from test_strata_tokenizer import load_tokenizer
from serve.frontend import ChatTemplate

def build_multiturn_prompts(template: ChatTemplate, turn_sizes: list[int], conv_id: int = 1) -> list[str]:
    """Generates expanding multi-turn prompt strings using real code excerpts and chat formatting."""
    system_prompt = (
        f"You are Strata Coder (Session {conv_id}), an advanced coding assistant specialized in high-performance C++, CUDA, HIP, "
        "and Python systems programming. Always produce correct, robust, and well-documented implementations."
    )
    
    # Base code chunk to expand conversations
    code_snippet = f"""
// Session {conv_id} Module
template <typename T, int BlockSize>
__global__ void matrix_vector_kernel_s{conv_id}(const T* __restrict__ A, const T* __restrict__ x, T* __restrict__ y, int M, int N) {{
    __shared__ T shared_x[BlockSize];
    int row = blockIdx.x * blockDim.x + threadIdx.x;
    T sum = 0;
    for (int col_block = 0; col_block < N; col_block += BlockSize) {{
        if (col_block + threadIdx.x < N) {{
            shared_x[threadIdx.x] = x[col_block + threadIdx.x];
        }} else {{
            shared_x[threadIdx.x] = 0;
        }}
        __syncthreads();
        if (row < M) {{
            #pragma unroll
            for (int k = 0; k < BlockSize; ++k) {{
                if (col_block + k < N) {{
                    sum += A[row * N + col_block + k] * shared_x[k];
                }}
            }}
        }}
        __syncthreads();
    }}
    if (row < M) {{
        y[row] = sum;
    }}
}}
"""
    
    messages = [{"role": "system", "content": system_prompt}]
    prompts = []
    
    for i, target_tokens in enumerate(turn_sizes, start=1):
        repeats = max(1, (target_tokens - len(messages) * 100) // 150)
        user_content = (
            f"Turn {i} (Session {conv_id}): Please review, optimize, and profile the following kernel implementation "
            f"for AMD RDNA3 architecture with wave32 execution.\n\n"
            + (code_snippet * repeats)
        )
        messages.append({"role": "user", "content": user_content})
        rendered = template.render(messages)
        prompts.append(rendered)
        messages.append({
            "role": "assistant",
            "content": f"Understood. Here is the optimized analysis for session {conv_id} turn {i} focusing on dual-issue wave32 vector instructions."
        })
        
    return prompts

def run_benchmark():
    pack_dir = os.environ.get("STRATA_TOKENIZER", str(Path(__file__).resolve().parents[2] / "Strata-data" / "packs" / "coder-iq1_m" / "tokenizer"))
    os.environ["STRATA_TOKENIZER"] = pack_dir
    print(f"================================================================================")
    print(f"Strata v0.1.45 Component 4: Prompt Tokenizer Prefix Caching Benchmark")
    print(f"Tokenizer Pack: {pack_dir}")
    print(f"================================================================================")
    
    tk = load_tokenizer()
    if tk is None:
        print("ERROR: Failed to load tokenizer pack.")
        sys.exit(1)
        
    template = ChatTemplate(ROOT / "serve" / "chat_template.jinja")
    
    # 5 progressive turn sizes up to ~32K tokens
    turn_sizes = [2048, 8192, 16384, 24576, 32768]
    prompts = build_multiturn_prompts(template, turn_sizes)
    
    print("\n--- Validating Exact Bitwise Token Parity across all turns ---")
    enc = ST.PromptEncoder(tk, keep=4)
    parity_all = True
    actual_tokens = []
    
    for turn_idx, p in enumerate(prompts, start=1):
        full_ids = tk.encode(p, parse_special=True)
        cached_ids = enc.encode(p)
        actual_tokens.append(len(full_ids))
        
        matches = (full_ids == cached_ids)
        if not matches:
            parity_all = False
            print(f"  Turn {turn_idx}: FAIL! Length full={len(full_ids)}, cached={len(cached_ids)}")
        else:
            print(f"  Turn {turn_idx} ({len(full_ids):5d} tokens): PASS (100% bitwise identical, {enc.last_reused:5d} chars reused)")
            
    if not parity_all:
        print("\nFATAL: Bitwise parity check failed!")
        sys.exit(1)
    print("Bitwise Parity Gate: PASS (100% identical token sequence across all turns)")
    
    # Benchmark runs
    REPEATS = 5
    print(f"\n--- Measuring CPU Tokenization Latency ({REPEATS} iterations per turn) ---")
    
    full_times = [[] for _ in turn_sizes]
    cached_times = [[] for _ in turn_sizes]
    chars_reused_records = []
    
    for rep in range(REPEATS):
        # Fresh encoder each repetition to measure cold start on turn 1
        rep_enc = ST.PromptEncoder(tk, keep=4)
        for turn_idx, p in enumerate(prompts):
            # Full encode timing
            t0 = time.perf_counter()
            full_ids = tk.encode(p, parse_special=True)
            t1 = time.perf_counter()
            full_times[turn_idx].append((t1 - t0) * 1000.0) # ms
            
            # Cached encode timing
            t2 = time.perf_counter()
            cached_ids = rep_enc.encode(p)
            t3 = time.perf_counter()
            cached_times[turn_idx].append((t3 - t2) * 1000.0) # ms
            
            if rep == 0:
                chars_reused_records.append(rep_enc.last_reused)
                
    # Output Table
    print("\n" + "=" * 90)
    print(f"{'Turn':<6} | {'Tokens':<8} | {'Full Encode (ms)':<18} | {'Prefix Encode (ms)':<18} | {'Speedup':<10} | {'Chars Reused':<12}")
    print("-" * 90)
    
    total_full_ms = 0.0
    total_cached_ms = 0.0
    
    results_summary = []
    
    for idx, tokens in enumerate(actual_tokens, start=1):
        f_med = sorted(full_times[idx - 1])[REPEATS // 2]
        c_med = sorted(cached_times[idx - 1])[REPEATS // 2]
        speedup = f_med / max(c_med, 0.001)
        total_full_ms += f_med
        total_cached_ms += c_med
        reused = chars_reused_records[idx - 1]
        
        results_summary.append({
            "turn": idx,
            "tokens": tokens,
            "full_ms": round(f_med, 2),
            "prefix_ms": round(c_med, 2),
            "speedup": round(speedup, 2),
            "chars_reused": reused
        })
        
        print(f"Turn {idx:<2} | {tokens:<8d} | {f_med:8.2f} ms         | {c_med:8.2f} ms         | {speedup:6.2f}x    | {reused:<12d}")
        
    session_speedup = total_full_ms / max(total_cached_ms, 0.001)
    print("-" * 90)
    print(f"{'Total':<6} | {sum(actual_tokens):<8d} | {total_full_ms:8.2f} ms         | {total_cached_ms:8.2f} ms         | {session_speedup:6.2f}x    | CPU Saved: {total_full_ms - total_cached_ms:.1f} ms")
    print("=" * 90)
    
    # Multi-session interleaved cache test
    print("\n--- Testing Multi-Conversation Cache Slot Switching (keep=4) ---")
    multi_enc = ST.PromptEncoder(tk, keep=4)
    # 4 distinct conversations
    convs = [build_multiturn_prompts(template, [2048, 4096], conv_id=c_id) for c_id in range(1, 5)]
    # Encode turn 1 of each conversation
    for c_idx, c_prompts in enumerate(convs, start=1):
        multi_enc.encode(c_prompts[0])
    print(f"  Populated 4 distinct conversation cache slots. Active entries: {len(multi_enc.entries)}")
    
    # Resume each conversation at turn 2 (interleaved)
    multi_turn2_reused = []
    for c_idx, c_prompts in enumerate(convs, start=1):
        multi_enc.encode(c_prompts[1])
        multi_turn2_reused.append(multi_enc.last_reused)
        print(f"  Resumed Conv {c_idx} at Turn 2: {multi_enc.last_reused} chars reused from slot")
        
    all_interleaved_reused = all(r > 0 for r in multi_turn2_reused)
    print(f"Interleaved Multi-Conversation Slot Retention: {'PASS' if all_interleaved_reused else 'FAIL'}")
    
    # Save benchmark json output
    output_data = {
        "benchmark": "PromptEncoder_Prefix_Caching",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "tokenizer_pack": pack_dir,
        "turns": results_summary,
        "total_full_ms": round(total_full_ms, 2),
        "total_cached_ms": round(total_cached_ms, 2),
        "session_speedup": round(session_speedup, 2),
        "cpu_time_saved_ms": round(total_full_ms - total_cached_ms, 2),
        "multi_tenant_slot_retention_pass": all_interleaved_reused
    }
    
    out_path = ROOT / "bench" / "results" / "custom_tokenizer_bench_results.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output_data, indent=2), encoding="utf-8")
    print(f"\nSaved benchmark metrics to {out_path}")

if __name__ == "__main__":
    run_benchmark()
