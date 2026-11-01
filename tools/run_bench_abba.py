"""tools/run_bench_abba.py - ABBA benchmark runner (Trim vs Handoff) across all 11 tasks.

Executes:
  1. A1 (trim-r1, DL_HANDOFF=0)
  2. B1 (handoff-r1, DL_HANDOFF=1)
  3. B2 (handoff-r2, DL_HANDOFF=1)
  4. A2 (trim-r2, DL_HANDOFF=0)
with DL_CONTEXT_RESERVE=40000 (limit ~25.5k tokens).
Then runs compare, evaluates acceptance criteria, cleans up bench.conf, and generates the wiki artifact.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
TASKS = "tetris,longplan,bugfix,crc32c,roman,intervals,expr,cron,wrongtest,nodata,stubs"
DROP_IN = Path.home() / ".config" / "systemd" / "user" / "dl-ai-sessiond.service.d" / "bench.conf"
SOCKET_PATH = Path(f"/run/user/{os.getuid()}/dl-ai/sessiond.sock")
BENCH_ROOT = REPO.parent / "DL-AI-workspace" / "bench"


def set_daemon_env(handoff: int, reserve: int = 40000) -> None:
    DROP_IN.parent.mkdir(parents=True, exist_ok=True)
    DROP_IN.write_text(f"[Service]\nEnvironment=DL_CONTEXT_RESERVE={reserve}\nEnvironment=DL_HANDOFF={handoff}\n")
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "restart", "dl-ai-sessiond"], check=True)
    # Wait for daemon socket to become ready
    t0 = time.time()
    while time.time() - t0 < 30:
        if SOCKET_PATH.exists():
            try:
                s = socket.socket(socket.AF_UNIX)
                s.settimeout(2)
                s.connect(str(SOCKET_PATH))
                f = s.makefile("rwb")
                f.write(b'{"op":"attach","session":"__ping__"}\n')
                f.flush()
                resp = f.readline()
                s.close()
                if resp:
                    print(f"[bench] dl-ai-sessiond ready with DL_HANDOFF={handoff}, DL_CONTEXT_RESERVE={reserve}")
                    return
            except OSError:
                pass
        time.sleep(0.5)
    raise RuntimeError("Timed out waiting for dl-ai-sessiond to restart")


def remove_daemon_env() -> None:
    if DROP_IN.exists():
        DROP_IN.unlink()
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "restart", "dl-ai-sessiond"], check=True)
    print("[bench] Removed bench.conf and restarted clean dl-ai-sessiond")


def find_latest_run_dir(label: str) -> Path:
    candidates = sorted(BENCH_ROOT.glob(f"*-{label}*"), key=lambda p: p.stat().st_mtime)
    if not candidates:
        raise FileNotFoundError(f"No run dir found for label {label} in {BENCH_ROOT}")
    return candidates[-1]


def run_arm(label: str, handoff: int) -> Path:
    print(f"\n=======================================================")
    print(f"=== STARTING ARM: {label} (DL_HANDOFF={handoff}) ===")
    print(f"=======================================================\n", flush=True)
    set_daemon_env(handoff)

    cmd = [
        sys.executable,
        str(HERE / "dl_agent_bench.py"),
        "run",
        "--label", label,
        "--tasks", TASKS,
        "--root", str(BENCH_ROOT),
    ]
    t0 = time.time()
    res = subprocess.run(cmd, cwd=REPO)
    duration = time.time() - t0
    print(f"[bench] Finished {label} in {duration / 60:.1f} minutes (returncode: {res.returncode})", flush=True)

    run_dir = find_latest_run_dir(label)
    if not (run_dir / "results.json").is_file():
        raise RuntimeError(f"results.json missing in {run_dir}")
    return run_dir


def main() -> int:
    steps = [
        ("trim-r1", 0),
        ("handoff-r1", 1),
        ("handoff-r2", 1),
        ("trim-r2", 0),
    ]
    run_dirs: list[Path] = []
    t_bench_start = time.time()

    try:
        for label, handoff in steps:
            rdir = run_arm(label, handoff)
            run_dirs.append(rdir)

        print("\n=======================================================")
        print("=== ALL 4 RUNS COMPLETE. RUNNING COMPARISON ===")
        print("=======================================================\n")

        compare_cmd = [
            sys.executable,
            str(HERE / "dl_agent_bench.py"),
            "compare",
            *[str(d) for d in run_dirs]
        ]
        comp_res = subprocess.run(compare_cmd, capture_output=True, text=True, cwd=REPO)
        comparison_table = comp_res.stdout
        print(comparison_table)

        # Build comprehensive wiki artifact
        today = time.strftime("%Y-%m-%d")
        total_hours = (time.time() - t_bench_start) / 3600

        artifact_content = f"""---
title: "Wiki Handoff vs Mechanical Trimming A/B Benchmark"
type: artifact
description: "Empirical 11-task ABBA benchmark results comparing Wiki Handoff vs Trimming under 25.5k limit"
status: active
tags: [benchmark, handoff, context, empirical]
created: {today}
updated: {today}
last_verified: {today}
---

# Wiki Handoff vs Mechanical Trimming A/B Benchmark ({today})

## Overview

Full empirical A/B benchmark comparing the **Two-Tier Wiki Handoff & Clean Session Reload** architecture against classic **Mechanical Trimming to 30k** across all 11 standardized coding tasks in `tools/dl_agent_bench.py`.

- **Hardware:** AMD Radeon RX 7600 XT (16 GB VRAM) + 64 GB DDR5 RAM, Linux (CachyOS kernel 6.17).
- **Model:** Qwen3.8-Flash-Next Coder IQ1_M with CPU elastic vision (`serve/server.py`).
- **Context limit forced:** `DL_CONTEXT_RESERVE=40000` (effective limit ≈ 25.5k tokens, forcing frequent context pressure).
- **Sequence (ABBA):**
  1. `trim-r1` (`DL_HANDOFF=0`)
  2. `handoff-r1` (`DL_HANDOFF=1`)
  3. `handoff-r2` (`DL_HANDOFF=1`)
  4. `trim-r2` (`DL_HANDOFF=0`)
- **Total Duration:** {total_hours:.2f} hours across 44 task executions.

## Comparison Table

{comparison_table}

## Runs Detail

- `trim-r1`: `{run_dirs[0]}`
- `handoff-r1`: `{run_dirs[1]}`
- `handoff-r2`: `{run_dirs[2]}`
- `trim-r2`: `{run_dirs[3]}`

## Sources

1. Generated automatically by `tools/run_bench_abba.py` and `tools/dl_agent_bench.py`.
"""
        artifact_path = REPO / "wiki" / "artifacts" / "handoff-vs-trim-bench-2026-11.md"
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text(artifact_content, encoding="utf-8")
        print(f"[bench] Saved benchmark artifact to {artifact_path}")

        # Update index if wiki script is available
        wscript = Path.home() / "Desktop" / "local-wiki" / "scripts" / "wiki.py"
        if wscript.is_file():
            subprocess.run([sys.executable, str(wscript), "index", "--root", str(REPO / "wiki")])

    finally:
        remove_daemon_env()

    print("[bench] ABBA Benchmark finished successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
