#!/usr/bin/env python3
"""antigravity_local.py - Local Antigravity Agent CLI powered by Strata Qwen3.8-Flash-Next Coder.

Provides an interactive Antigravity coding experience that runs 100% locally on
the Strata engine at http://127.0.0.1:8080.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import readline
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# ANSI colors & formatting
C_RESET = "\033[0m"
C_BOLD = "\033[1m"
C_DIM = "\033[2m"
C_PURPLE = "\033[38;5;141m"
C_CYAN = "\033[36m"
C_GREEN = "\033[32m"
C_YELLOW = "\033[33m"
C_RED = "\033[31m"
C_GRAY = "\033[90m"

DEFAULT_URL = os.environ.get("STRATA_URL", "http://127.0.0.1:8080").removesuffix("/v1")
DEFAULT_API_KEY = os.environ.get("STRATA_API_KEY", "REDACTED")


def print_banner(workspace: Path, model_name: str, think_level: str):
    banner = f"""
{C_PURPLE}      ▄▀▀▄        {C_BOLD}Antigravity Local Agent{C_RESET} {C_GRAY}(v2.0){C_RESET}
{C_PURPLE}     ▀▀▀▀▀▀       {C_CYAN}Strata Qwen3.8-Flash-Next Coder (IQ1_M){C_RESET}
{C_PURPLE}    ▀▀▀▀▀▀▀▀      {C_DIM}Engine:{C_RESET} {DEFAULT_URL} {C_GREEN}[ROCm Active]{C_RESET}
{C_PURPLE}   ▄▀▀    ▀▀▄     {C_DIM}Workspace:{C_RESET} {workspace}
{C_PURPLE}  ▄▀▀      ▀▀▄    {C_DIM}Reasoning Effort:{C_RESET} {C_YELLOW}{think_level}{C_RESET}
{C_GRAY}─────────────────────────────────────────────────────────────────────────────{C_RESET}
{C_DIM}Commands: /clear, /think <level>, /status, /cloud (Gemini), !<cmd> (shell), @file{C_RESET}
{C_GRAY}─────────────────────────────────────────────────────────────────────────────{C_RESET}
"""
    sys.stdout.write(banner)
    sys.stdout.flush()


def resolve_file_references(prompt: str, workspace: Path) -> str:
    pattern = r"@([a-zA-Z0-9_\-\.\/]+)"
    matches = list(re.finditer(pattern, prompt))
    if not matches:
        return prompt

    offset = 0
    new_prompt = prompt
    for m in matches:
        fpath_str = m.group(1)
        p = (workspace / fpath_str).resolve()
        if not p.is_file():
            p = Path(fpath_str).resolve()
        if p.is_file():
            try:
                content = p.read_text(encoding="utf-8", errors="replace")
                ext = p.suffix.lstrip(".") or "text"
                rel_path = p.relative_to(workspace) if p.is_relative_to(workspace) else p
                replacement = f"\n\n```file:{rel_path}\n{content}\n```\n"
                start, end = m.start() + offset, m.end() + offset
                new_prompt = new_prompt[:start] + replacement + new_prompt[end:]
                offset += len(replacement) - (end - start)
            except Exception as e:
                sys.stderr.write(f"{C_YELLOW}Warning: Could not read @{fpath_str}: {e}{C_RESET}\n")
    return new_prompt


def stream_chat_completion(messages: list[dict], url: str, api_key: str,
                           think_level: str = "low", max_tokens: int = 4096,
                           temperature: float = 0.2):
    endpoint = f"{url.rstrip('/')}/v1/chat/completions"
    payload = {
        "model": "strata",
        "messages": messages,
        "max_tokens": max_tokens,
        "reasoning_effort": think_level,
        "temperature": temperature,
        "stream": True,
    }
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
    )

    t0 = time.time()
    reasoning_started = False
    reasoning_closed = False
    full_reasoning = []
    full_content = []
    tok_count = 0
    timings = {}

    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            for raw_line in resp:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line or line.startswith(":"):
                    continue
                if line.startswith("data: "):
                    data_str = line[6:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    if "timings" in chunk:
                        timings = chunk["timings"]

                    delta = (chunk.get("choices") or [{}])[0].get("delta") or {}

                    # 1. Reasoning chunk
                    reasoning_chunk = delta.get("reasoning_content")
                    if reasoning_chunk:
                        tok_count += 1
                        if not reasoning_started:
                            sys.stdout.write(f"\n{C_GRAY}{C_DIM}🧠 Thinking:{C_RESET} {C_GRAY}{C_DIM}")
                            reasoning_started = True
                        sys.stdout.write(reasoning_chunk)
                        sys.stdout.flush()
                        full_reasoning.append(reasoning_chunk)

                    # 2. Main content chunk
                    content_chunk = delta.get("content")
                    if content_chunk:
                        tok_count += 1
                        if reasoning_started and not reasoning_closed:
                            sys.stdout.write(f"{C_RESET}\n\n")
                            reasoning_closed = True
                        sys.stdout.write(content_chunk)
                        sys.stdout.flush()
                        full_content.append(content_chunk)

            if reasoning_started and not reasoning_closed:
                sys.stdout.write(f"{C_RESET}\n")

            sys.stdout.write("\n")
            sys.stdout.flush()

    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Strata API HTTP {e.code}: {err}")
    except Exception as e:
        raise RuntimeError(f"Connection failed to Strata at {endpoint}: {e}")

    dt = time.time() - t0
    rate = tok_count / dt if dt > 0 else 0
    return {
        "reasoning": "".join(full_reasoning),
        "content": "".join(full_content),
        "tokens": tok_count,
        "wall_time": dt,
        "rate": rate,
        "timings": timings,
    }


def execute_shell_command(cmd: str, cwd: Path) -> str:
    print(f"\n{C_PURPLE}Running:{C_RESET} {cmd}\n")
    try:
        res = subprocess.run(cmd, shell=True, cwd=cwd, text=True, capture_output=True)
        if res.stdout:
            sys.stdout.write(res.stdout)
        if res.stderr:
            sys.stderr.write(f"{C_RED}{res.stderr}{C_RESET}")
        output = (res.stdout + ("\n" + res.stderr if res.stderr else "")).strip()
        print(f"\n{C_DIM}[Command exited with code {res.returncode}]{C_RESET}\n")
        return output
    except Exception as e:
        print(f"{C_RED}Error running command: {e}{C_RESET}")
        return f"Error: {e}"


def check_status(url: str, api_key: str):
    endpoint = f"{url.rstrip('/')}/health"
    req = urllib.request.Request(endpoint, headers={"Authorization": f"Bearer {api_key}"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            print(f"\n{C_BOLD}Strata Engine Status:{C_RESET}")
            print(f"  • Status:     {C_GREEN}{data.get('status', 'ok')}{C_RESET}")
            print(f"  • Model:      {C_CYAN}{data.get('model', 'unknown')}{C_RESET}")
            print(f"  • Context:    {data.get('max_context', 0):,} tokens")
            print(f"  • Accelerator: ROCm GPU + Resident RAM\n")
    except Exception as e:
        print(f"{C_RED}Failed to reach Strata at {url}: {e}{C_RESET}\n")


def build_system_prompt(workspace: Path) -> str:
    return (
        "You are Antigravity Local Agent, an elite AI pair programmer and software engineer "
        "powered by Strata's local Qwen3.8-Flash-Next Coder model running on local GPU acceleration.\n"
        f"You are operating inside the developer's workspace at: {workspace}.\n\n"
        "Guidelines:\n"
        "- Give clear, concise, and direct explanations.\n"
        "- When writing or modifying code, provide complete, robust implementations.\n"
        "- When proposing bash shell commands to run, wrap them in ```bash ... ``` code blocks.\n"
        "- Keep the workflow focused, fast, and helpful."
    )


def interactive_loop(workspace: Path, url: str, api_key: str, think_level: str = "low", auto_exec: bool = False):
    history_file = Path.home() / ".gemini" / "antigravity_local_history"
    history_file.parent.mkdir(parents=True, exist_ok=True)
    if history_file.is_file():
        try:
            readline.read_history_file(str(history_file))
        except Exception:
            pass

    system_prompt = build_system_prompt(workspace)
    messages: list[dict] = [{"role": "system", "content": system_prompt}]

    print_banner(workspace, "Qwen3.8-Flash-Next Coder", think_level)

    try:
        while True:
            try:
                raw_input = input(f"{C_PURPLE}antigravity{C_RESET} > ")
            except EOFError:
                print("\nExiting Antigravity Local Agent.")
                break
            except KeyboardInterrupt:
                print("\n")
                continue

            prompt = raw_input.strip()
            if not prompt:
                continue

            # Command dispatch
            if prompt in ("/exit", "/quit", "exit", "quit"):
                print("Exiting Antigravity Local Agent.")
                break
            elif prompt in ("/clear", "/reset"):
                messages = [{"role": "system", "content": system_prompt}]
                print(f"{C_GREEN}✓ Conversation reset.{C_RESET}\n")
                continue
            elif prompt == "/help":
                print(f"\n{C_BOLD}Antigravity Local Commands:{C_RESET}")
                print(f"  /clear, /reset        Reset conversation memory")
                print(f"  /think <none|low|med|high> Set reasoning effort level")
                print(f"  /status               Check Strata server health")
                print(f"  /cloud                Switch to upstream Google Gemini agy")
                print(f"  !<shell command>      Execute command directly in workspace")
                print(f"  @filename             Inject file content into your prompt\n")
                continue
            elif prompt.startswith("/think"):
                parts = prompt.split()
                if len(parts) > 1 and parts[1].lower() in ("none", "low", "medium", "med", "high"):
                    val = parts[1].lower()
                    if val == "med":
                        val = "medium"
                    think_level = val
                    print(f"{C_GREEN}✓ Reasoning effort set to: {think_level}{C_RESET}\n")
                else:
                    print(f"Current reasoning effort: {think_level}. Usage: /think [none|low|medium|high]\n")
                continue
            elif prompt in ("/status", "/model"):
                check_status(url, api_key)
                continue
            elif prompt == "/cloud":
                print(f"{C_YELLOW}Switching to Google Cloud agy CLI...{C_RESET}\n")
                subprocess.run(["/home/damirl/.local/bin/agy"], cwd=workspace)
                print_banner(workspace, "Qwen3.8-Flash-Next Coder", think_level)
                continue
            elif prompt.startswith("!"):
                cmd = prompt[1:].strip()
                if cmd:
                    execute_shell_command(cmd, workspace)
                continue

            # File injection
            resolved_prompt = resolve_file_references(prompt, workspace)
            messages.append({"role": "user", "content": resolved_prompt})

            try:
                res = stream_chat_completion(
                    messages=messages,
                    url=url,
                    api_key=api_key,
                    think_level=think_level,
                )
                assistant_text = res["content"]
                messages.append({"role": "assistant", "content": assistant_text})

                # Stats footer
                rate_str = f" · {res['rate']:.1f} t/s" if res['rate'] > 0 else ""
                print(f"{C_GRAY}[{res['tokens']} tokens in {res['wall_time']:.1f}s{rate_str}]{C_RESET}\n")

                # Detect bash command proposal
                bash_blocks = re.findall(r"```(?:bash|sh)\n([\s\S]*?)\n```", assistant_text)
                if bash_blocks:
                    for block in bash_blocks:
                        cmd_to_run = block.strip()
                        if auto_exec:
                            execute_shell_command(cmd_to_run, workspace)
                        else:
                            try:
                                ans = input(f"{C_CYAN}Run suggested command?{C_RESET} ({cmd_to_run}) [y/N]: ").strip().lower()
                                if ans in ("y", "yes"):
                                    cmd_out = execute_shell_command(cmd_to_run, workspace)
                                    messages.append({
                                        "role": "user",
                                        "content": f"Command output from `{cmd_to_run}`:\n```\n{cmd_out}\n```"
                                    })
                            except (KeyboardInterrupt, EOFError):
                                print("\nSkipped.")
                                break

            except Exception as e:
                print(f"{C_RED}Error during inference: {e}{C_RESET}\n")
                if messages and messages[-1].get("role") == "user":
                    messages.pop()

    finally:
        try:
            readline.write_history_file(str(history_file))
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(description="Antigravity Local CLI on Strata Engine")
    parser.add_argument("--workspace", default=os.getcwd(), help="Workspace directory")
    parser.add_argument("--url", default=DEFAULT_URL, help="Strata URL")
    parser.add_argument("--api-key", default=DEFAULT_API_KEY, help="Strata API Key")
    parser.add_argument("--think", default="low", choices=["none", "low", "medium", "high"], help="Reasoning effort")
    parser.add_argument("-p", "--prompt", help="Run single prompt non-interactively and exit")
    parser.add_argument("--auto", "--dangerously-skip-permissions", action="store_true", help="Auto-run suggested commands")

    args = parser.parse_args()
    ws = Path(args.workspace).resolve()

    if args.prompt:
        resolved = resolve_file_references(args.prompt, ws)
        messages = [
            {"role": "system", "content": build_system_prompt(ws)},
            {"role": "user", "content": resolved}
        ]
        try:
            stream_chat_completion(messages, args.url, args.api_key, think_level=args.think)
            sys.exit(0)
        except Exception as e:
            sys.stderr.write(f"Error: {e}\n")
            sys.exit(1)

    interactive_loop(ws, args.url, args.api_key, think_level=args.think, auto_exec=args.auto)


if __name__ == "__main__":
    main()
