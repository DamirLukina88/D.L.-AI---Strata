"""The terminal client: banner, slash commands, status, export.

Moved out of dl_cli.py without changes; see dl_cli.py for the entry point and the names tests patch."""
from __future__ import annotations

from pathlib import Path
import datetime
import os
import re
import readline
import subprocess
import sys
try:
    from .dl_common import (
    C_ACCENT,
    C_ACCENT_BOLD,
    C_ACCENT_SOFT,
    C_BOLD,
    C_CYAN,
    C_GREEN,
    C_INK,
    C_INK_SOFT,
    C_LINE,
    C_MUTED,
    C_RED,
    C_RESET,
    C_YELLOW,
    DEFAULT_URL,
    cli as _cli,
    dl_mcp,
    dl_memory,
    format_health_card,
    get_system_health,
    memory_store,
    tool_git_diff_audit,
    tool_scan_secrets,
    tool_smart_test_runner,
    tool_syntax_guard,
)
except ImportError:
    from dl_common import (
    C_ACCENT,
    C_ACCENT_BOLD,
    C_ACCENT_SOFT,
    C_BOLD,
    C_CYAN,
    C_GREEN,
    C_INK,
    C_INK_SOFT,
    C_LINE,
    C_MUTED,
    C_RED,
    C_RESET,
    C_YELLOW,
    DEFAULT_URL,
    cli as _cli,
    dl_mcp,
    dl_memory,
    format_health_card,
    get_system_health,
    memory_store,
    tool_git_diff_audit,
    tool_scan_secrets,
    tool_smart_test_runner,
    tool_syntax_guard,
)
try:
    from .dl_media import build_user_message_content
except ImportError:
    from dl_media import build_user_message_content
try:
    from .dl_memory_tools import MEMORY_SLASH, memory_slash
except ImportError:
    from dl_memory_tools import MEMORY_SLASH, memory_slash
try:
    from .dl_prompt import build_dl_system_prompt, plan_progress, save_approved_plan
except ImportError:
    from dl_prompt import build_dl_system_prompt, plan_progress, save_approved_plan
try:
    from .dl_status import (
    chat_settings_summary,
    check_status,
    format_messages_to_markdown,
    sync_current_chat_state,
)
except ImportError:
    from dl_status import (
    chat_settings_summary,
    check_status,
    format_messages_to_markdown,
    sync_current_chat_state,
)
try:
    from .dl_tools_impl import tool_context7_resolve, tool_exa_web_search
except ImportError:
    from dl_tools_impl import tool_context7_resolve, tool_exa_web_search
try:
    from .dl_tools_schema import find_wiki_script, resolve_wiki_root
except ImportError:
    from dl_tools_schema import find_wiki_script, resolve_wiki_root
try:
    from .dl_wiki_legacy import (
    perform_wiki_backup,
    perform_wiki_lint,
    perform_wiki_remember,
    tool_local_wiki,
)
except ImportError:
    from dl_wiki_legacy import (
    perform_wiki_backup,
    perform_wiki_lint,
    perform_wiki_remember,
    tool_local_wiki,
)


def print_banner(workspace: Path, settings_text: str, mode: str = "act"):
    mode_badge = f"{C_YELLOW}[PLAN MODE]{C_RESET}" if mode == "plan" else f"{C_GREEN}[ACT MODE]{C_RESET}"
    store = memory_store()
    wroot = store or resolve_wiki_root(workspace)
    if store:
        wiki_badge = f"{C_GREEN}[{store.name} · {dl_memory.resolve_project_slug(workspace, store)}]{C_RESET}"
    else:
        wiki_badge = f"{C_GREEN}[Active: {wroot.name}]{C_RESET}" if wroot else f"{C_MUTED}[Inactive]{C_RESET}"
    tools_str = "bash, files, audit, health, tests, memory, exa, docs" if wroot else "bash, files, audit, health, tests, exa, docs"
    rocm_badge = f"{C_GREEN}[ROCm GPU Active]{C_RESET}"

    card_width = 79

    def _row(text: str) -> str:
        plain = re.sub(r'\033\[[0-9;]*m', '', text)
        pad = max(0, card_width - 4 - len(plain))
        return f"{C_LINE}│{C_RESET}  {text}{' ' * pad}{C_LINE}│{C_RESET}\n"

    top_border = f"{C_LINE}╭{'─' * (card_width - 2)}╮{C_RESET}\n"
    mid_border = f"{C_LINE}├{'─' * (card_width - 2)}┤{C_RESET}\n"
    bot_border = f"{C_LINE}╰{'─' * (card_width - 2)}╯{C_RESET}\n"

    ws_str = str(workspace)
    if len(ws_str) > 52:
        ws_str = "..." + ws_str[-49:]

    out = [
        "\n",
        top_border,
        _row(f"{C_ACCENT_BOLD}✦ CLI{C_RESET}  {C_MUTED}·{C_RESET}  {C_INK_SOFT}Autonomous Local Coding Agent{C_RESET} {C_MUTED}(v2.0){C_RESET}"),
        mid_border,
        _row(f"{C_MUTED}Model{C_RESET}     : {C_INK}Qwen3.8-Flash-Next Coder{C_RESET} {C_MUTED}(IQ1_M MOE · Local){C_RESET}"),
        _row(f"{C_MUTED}Engine{C_RESET}    : {C_INK_SOFT}{DEFAULT_URL}{C_RESET}  {rocm_badge}"),
        _row(f"{C_MUTED}Workspace{C_RESET} : {C_INK_SOFT}{ws_str}{C_RESET}"),
        _row(f"{C_MUTED}Status{C_RESET}    : {mode_badge}  {C_MUTED}·{C_RESET}  {'Memory' if store else 'Wiki'}: {wiki_badge}"),
        _row(f"{C_MUTED}Settings{C_RESET}  : {C_ACCENT_SOFT}{settings_text[:62]}{C_RESET}"),
        _row(f"{C_MUTED}Tools{C_RESET}     : {C_INK_SOFT}{tools_str}{C_RESET}"),
        _row(f"{C_MUTED}Commands{C_RESET}  : {C_INK_SOFT}/plan, /act, /save, /health, /diff, /test, /memory, !<bash>{C_RESET}"),
        bot_border,
        "\n"
    ]
    sys.stdout.write("".join(out))
    sys.stdout.flush()


def interactive_loop(workspace: Path, url: str, api_key: str, initial_mode: str = "act"):
    history_file = Path.home() / ".config" / "dl" / "cli_history"
    history_file.parent.mkdir(parents=True, exist_ok=True)
    if history_file.is_file():
        try:
            readline.read_history_file(str(history_file))
        except Exception:
            pass

    current_mode = initial_mode
    prefix_mode = False
    yolo = False                  # /yolo: destructive actions run without asking (this session only)
    mcp = dl_mcp.McpRegistry(surface="terminal",
                             notify=lambda t, level="info": print(f"{C_MUTED}  ⚙ MCP {t}{C_RESET}")) if dl_mcp else None
    pending_prompt = None         # a command queued by the CLI itself (plan approved -> /act)
    plan_file = None              # the approved plan (PLAN.md) the done check holds the agent to
    custom_prefix = None
    system_prompt = build_dl_system_prompt(workspace, mode=current_mode)
    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    sync_current_chat_state(messages, workspace)

    print_banner(workspace, chat_settings_summary(url, api_key), mode=current_mode)

    try:
        while True:
            prompt_prefix = f"{C_ACCENT_BOLD}dl{C_RESET} {C_YELLOW}(plan){C_RESET} {C_MUTED}›{C_RESET} " if current_mode == "plan" else f"{C_ACCENT_BOLD}dl{C_RESET} {C_MUTED}›{C_RESET} "
            try:
                raw_input, pending_prompt = (pending_prompt, None) if pending_prompt else (input(prompt_prefix), None)
            except EOFError:
                print("\nExiting D.L. CLI.")
                break
            except KeyboardInterrupt:
                print("\n")
                continue

            prompt = raw_input.strip()
            if not prompt:
                continue

            # Command dispatch
            if prompt in ("/exit", "/quit", "exit", "quit"):
                print("Exiting D.L. CLI.")
                break
            elif prompt in ("/clear", "/reset"):
                plan_file = None
                messages = [{"role": "system", "content": build_dl_system_prompt(workspace, mode=current_mode)}]
                sync_current_chat_state(messages, workspace)
                print(f"{C_GREEN}✓ D.L. memory reset ({current_mode.upper()} mode).{C_RESET}\n")
                continue
            elif prompt.split(" ", 1)[0] == "/planfile":
                arg = prompt[len("/planfile"):].strip()
                if arg.lower() in ("off", "none", "clear"):
                    plan_file = None
                    print(f"{C_MUTED}No active plan: the done check is off.{C_RESET}\n")
                elif arg:
                    pf = Path(arg).expanduser()
                    pf = pf if pf.is_absolute() else (workspace / pf)
                    if pf.is_file():
                        plan_file = str(pf.resolve())
                        _, o, d, _ = plan_progress(pf)
                        print(f"{C_MUTED}Active plan: {pf.name} ({len(d)} done, {len(o)} open).{C_RESET}\n")
                    else:
                        print(f"{C_YELLOW}No such file: {pf}{C_RESET}\n")
                else:
                    print(f"{C_MUTED}Active plan: {plan_file or 'none'}.{C_RESET}\n")
                continue
            elif prompt == "/help":
                print(f"\n{C_BOLD}D.L. CLI Commands:{C_RESET}")
                print(f"  /plan [query]         Toggle or enter Plan Mode (read-only research & design)")
                print(f"  /act, /execute [query] Switch to Act Mode (full execution & code edits)")
                print(f"  /cd <path>, cd <path> Switch active project working directory")
                print(f"  /save, /export, /markdown [file] Save current session as Markdown (with thinking & tools)")
                print(f"  /health, /sys         Real-time RAM, VRAM, Swap, ROCm GPU & server health card")
                print(f"  /diff, /audit         Semantic git diff audit (deletions, size, leaks, risks)")
                print(f"  /secrets [path]       Scan codebase or file for leaked API keys, tokens & certs")
                print(f"  /syntax [path]        Run AST syntax check on Python, JS, Bash, JSON, YAML")
                print(f"  /test [files]         Smart targeted test runner (pytest, unittest, npm, make)")
                print(f"  /wiki [search|lint|digest] Query or manage workspace Local Wiki")
                print(f"  /wiki-backup, /wiki backup  Back up session artifacts, plans, and outcomes to wiki/artifacts")
                print(f"  /wiki-lint, /wiki lint      Lint and repair project wiki (verify frontmatter, links, index)")
                print(f"  /remember <fact>            Save a fact, decision, or preference directly to Local Wiki")
                print(f"  /recall <topic>             Query Local Wiki knowledge with ranked citations")
                print(f"  /continue             Go on after the agent stopped at its tool-round limit")
                print(f"  /clear, /reset        Reset conversation memory")
                print(f"  /prefix [toggle|text] Set assistant seed prefix to suppress chatter")
                print(f"  /exa, /search <query> Direct Exa AI live web search")
                print(f"  /context7, /docs <lib> Direct Context7 library documentation lookup")
                print(f"  /status, /model       Check Strata server health")
                print(f"  /yolo                 Toggle approvals for destructive commands (on by default)")
                print(f"  /mcp [on|off NAME]    Tools & MCP servers (Home Assistant, Weather, Exa, DeepSeek, Knowledge suites): list or toggle")
                print(f"  /schedule             Scheduled jobs (they run in the session daemon: set them up in the Code tab or --attach)")
                print(f"  !<shell command>      Execute bash command directly in workspace")
                print(f"  @filename             Inject file content into your prompt")
                print(f"  /help                 This list")
                print(f"  /exit, /quit          Leave D.L. CLI\n")
                continue
            elif prompt == "/schedule" or prompt.startswith("/schedule "):
                try:
                    try:
                        from tools import dl_schedule
                    except ImportError:
                        import dl_schedule
                    jobs = dl_schedule.list_text()
                except ImportError:
                    jobs = "Scheduling is not available."
                print(f"\n{jobs}\n{C_MUTED}Scheduled jobs run in the session daemon: add or change them in the Code tab "
                      f"or with dl_cli.py --attach.{C_RESET}\n")
                continue
            elif prompt == "/mcp" or prompt.startswith("/mcp "):
                print(f"\n{mcp.command(prompt[4:]) if mcp else 'MCP support is not available.'}\n")
                continue
            elif prompt == "/yolo":
                yolo = not yolo
                print(f"{C_RED}⚠ YOLO on: destructive commands and writes outside the workspace run without asking.{C_RESET}\n"
                      if yolo else f"{C_GREEN}✓ Approvals back on for destructive actions.{C_RESET}\n")
                continue
            elif prompt.startswith("/prefix"):
                sub = prompt[7:].strip()
                if not sub or sub.lower() in ("toggle", "switch"):
                    if prefix_mode:
                        prefix_mode = False
                        custom_prefix = None
                        print(f"{C_MUTED}Prefix mode disabled (natural conversational output).{C_RESET}\n")
                    else:
                        prefix_mode = True
                        custom_prefix = "```"
                        print(f"{C_GREEN}Prefix mode enabled (seeds assistant turn with direct code block).{C_RESET}\n")
                elif sub.lower() in ("off", "disable", "stop"):
                    prefix_mode = False
                    custom_prefix = None
                    print(f"{C_MUTED}Prefix mode disabled.{C_RESET}\n")
                else:
                    prefix_mode = True
                    custom_prefix = sub
                    print(f"{C_GREEN}Prefix mode set to:{C_RESET} {custom_prefix}\n")
                continue
            elif prompt.startswith("/cd") or prompt.lower().startswith("cd ") or prompt == "cd":
                target_str = ""
                if prompt.startswith("/cd"):
                    target_str = prompt[3:].strip()
                elif prompt.lower().startswith("cd "):
                    target_str = prompt[3:].strip()

                if not target_str:
                    target_str = str(Path.home())

                cand = Path(target_str).expanduser()
                if not cand.is_absolute():
                    cand = (workspace / cand).resolve()
                else:
                    cand = cand.resolve()

                if not cand.exists():
                    try:
                        cand.mkdir(parents=True, exist_ok=True)
                        print(f"{C_MUTED}Created directory {cand}{C_RESET}")
                    except Exception as e:
                        print(f"{C_RED}Error: Directory not found and could not be created: {cand} ({e}){C_RESET}\n")
                        continue

                if not cand.is_dir():
                    print(f"{C_RED}Error: {cand} is not a directory.{C_RESET}\n")
                    continue

                workspace = cand
                try:
                    os.chdir(workspace)
                except Exception as e:
                    print(f"{C_RED}Error chdir to {workspace}: {e}{C_RESET}\n")

                messages[0] = {"role": "system", "content": build_dl_system_prompt(workspace, mode=current_mode)}
                sync_current_chat_state(messages, workspace)

                wroot = resolve_wiki_root(workspace)
                wiki_badge = f"{C_GREEN}[Active: {wroot.name}]{C_RESET}" if wroot else f"{C_MUTED}[Inactive: run /wiki to init]{C_RESET}"
                print(f"\n{C_GREEN}✓ Switched working directory to:{C_RESET} {C_BOLD}{workspace}{C_RESET}")
                print(f"{C_MUTED}  • Wiki Status: {wiki_badge}{C_RESET}\n")
                continue
            elif prompt.startswith("/plan"):
                sub = prompt[5:].strip()
                if not sub or sub.lower() in ("toggle", "switch"):
                    if current_mode == "plan":
                        current_mode = "act"
                        messages[0] = {"role": "system", "content": build_dl_system_prompt(workspace, mode=current_mode)}
                        msg_text = "⚡ Switched to ACT MODE. Full execution & file edits enabled."
                        print(f"{C_GREEN}{msg_text}{C_RESET}\n")
                    else:
                        current_mode = "plan"
                        messages[0] = {"role": "system", "content": build_dl_system_prompt(workspace, mode=current_mode)}
                        msg_text = "📋 Switched to PLAN MODE. File modifications disabled. Exploration & architecture enabled."
                        print(f"{C_YELLOW}{msg_text}{C_RESET}\n")
                    messages.append({"role": "user", "content": prompt})
                    messages.append({"role": "assistant", "content": msg_text})
                    sync_current_chat_state(messages, workspace)
                    continue
                elif sub.lower() in ("on", "start", "enable"):
                    current_mode = "plan"
                    messages[0] = {"role": "system", "content": build_dl_system_prompt(workspace, mode=current_mode)}
                    msg_text = "📋 Plan Mode enabled."
                    print(f"{C_YELLOW}{msg_text}{C_RESET}\n")
                    messages.append({"role": "user", "content": prompt})
                    messages.append({"role": "assistant", "content": msg_text})
                    sync_current_chat_state(messages, workspace)
                    continue
                elif sub.lower() in ("off", "stop", "disable"):
                    current_mode = "act"
                    messages[0] = {"role": "system", "content": build_dl_system_prompt(workspace, mode=current_mode)}
                    msg_text = "⚡ Plan Mode disabled. Switched to ACT MODE."
                    print(f"{C_GREEN}{msg_text}{C_RESET}\n")
                    messages.append({"role": "user", "content": prompt})
                    messages.append({"role": "assistant", "content": msg_text})
                    sync_current_chat_state(messages, workspace)
                    continue
                else:
                    current_mode = "plan"
                    messages[0] = {"role": "system", "content": build_dl_system_prompt(workspace, mode=current_mode)}
                    print(f"{C_YELLOW}📋 Entering PLAN MODE for: {sub}{C_RESET}\n")
                    prompt = sub
            elif prompt.startswith("/act") or prompt.startswith("/execute") or prompt.lower() in ("act", "execute") or prompt.lower().startswith("act ") or prompt.lower().startswith("execute "):
                if prompt.startswith("/act"):
                    sub = prompt[4:].strip()
                elif prompt.startswith("/execute"):
                    sub = prompt[8:].strip()
                elif prompt.lower().startswith("act"):
                    sub = prompt[3:].strip()
                else:
                    sub = prompt[7:].strip()
                saved = save_approved_plan(messages, workspace) if current_mode == "plan" else None
                if saved:
                    plan_file = str(saved)
                    print(f"{C_MUTED}Plan saved to {saved.name}; the agent works from it and ticks its Progress checklist.{C_RESET}")
                current_mode = "act"
                messages[0] = {"role": "system", "content": build_dl_system_prompt(workspace, mode=current_mode,
                                                                                   plan_file=plan_file)}
                if not sub:
                    msg_text = "⚡ Switched to ACT MODE. Executing agreed plan..."
                    print(f"{C_GREEN}{msg_text}{C_RESET}\n")
                    prompt = (f"Execute the approved plan in {saved.name} now, step by step, with the tool calls it needs (edits, writes, tests, commands). Keep its \"## Progress\" checklist current: tick each line (\"- [x]\") as soon as its own check passes - one line at a time, not when the whole section is done, and if you cannot go on, add a \"Blocked: <reason>\" line and say why. The task is done when every step is ticked."
                              if saved else "Proceed with executing the plan now. Perform the necessary tool calls (edits, writes, tests, commands) to implement the agreed plan.")
                else:
                    print(f"{C_GREEN}⚡ Executing in ACT MODE: {sub}{C_RESET}\n")
                    prompt = sub
            elif prompt.split(" ", 1)[0] == "/continue" or prompt.strip().lower() in ("continue", "keep going", "go on", "proceed"):
                parts = prompt.split(" ", 1)
                sub_arg = parts[1].strip() if len(parts) > 1 and parts[0] == "/continue" else ""
                prompt = sub_arg or _cli().CONTINUE_PROMPT
            elif memory_store() and prompt.split(" ", 1)[0].split("-", 1)[0] in MEMORY_SLASH:
                print("\n" + memory_slash(prompt, workspace, messages, mode=current_mode) + "\n")
                continue
            # Local Wiki slash command suite: /wiki-backup, /wiki backup, /wiki-lint, /wiki lint, /remember, /recall, /wiki
            elif (
                prompt.startswith("/wiki-backup") or prompt.startswith("/wiki backup") or
                prompt.startswith("/wiki-lint") or prompt.startswith("/wiki lint") or
                prompt.startswith("/remember") or prompt.startswith("/recall") or
                prompt.startswith("/wiki")
            ):
                wroot = resolve_wiki_root(workspace)
                wscript = find_wiki_script(workspace)
                if not wscript:
                    print(f"{C_RED}Error: local-wiki script (wiki.py) not found on system.{C_RESET}\n")
                    continue

                # Multi-command chaining parser: e.g. "/wiki-backup /wiki-lint update readme and git push"
                tokens = prompt.split()
                consumed_all = True
                remainder_prompt = ""

                # 1. /wiki-backup or /wiki backup
                if prompt.startswith("/wiki-backup") or prompt.startswith("/wiki backup"):
                    print(f"\n{C_ACCENT}✦ Running Local Wiki Artifact Backup...{C_RESET}")
                    backup_res = perform_wiki_backup(workspace, messages=messages)
                    print(f"{C_GREEN}✓ {backup_res}{C_RESET}\n")
                    # Check for chained commands
                    p_rest = prompt.replace("/wiki-backup", "", 1).replace("/wiki backup", "", 1).strip()
                    if p_rest.startswith("/wiki-lint") or p_rest.startswith("/wiki lint"):
                        print(f"{C_ACCENT}✦ Linting & repairing Local Wiki...{C_RESET}")
                        lint_res = perform_wiki_lint(workspace, auto_fix=True)
                        print(f"{C_MUTED}{lint_res}{C_RESET}\n")
                        p_rest = p_rest.replace("/wiki-lint", "", 1).replace("/wiki lint", "", 1).strip()
                    if p_rest:
                        print(f"{C_GREEN}⚡ Proceeding in ACT MODE: {p_rest}{C_RESET}\n")
                        prompt = p_rest
                        current_mode = "act"
                        messages[0] = {"role": "system", "content": build_dl_system_prompt(workspace, mode=current_mode)}
                        # continue into loop without 'continue'
                    else:
                        continue

                # 2. /wiki-lint or /wiki lint
                elif prompt.startswith("/wiki-lint") or prompt.startswith("/wiki lint"):
                    print(f"\n{C_ACCENT}✦ Linting & repairing Local Wiki...{C_RESET}")
                    lint_res = perform_wiki_lint(workspace, auto_fix=True)
                    print(f"{C_MUTED}{lint_res}{C_RESET}\n")
                    p_rest = prompt.replace("/wiki-lint", "", 1).replace("/wiki lint", "", 1).strip()
                    if p_rest:
                        print(f"{C_GREEN}⚡ Proceeding in ACT MODE: {p_rest}{C_RESET}\n")
                        prompt = p_rest
                        current_mode = "act"
                        messages[0] = {"role": "system", "content": build_dl_system_prompt(workspace, mode=current_mode)}
                    else:
                        continue

                # 3. /remember <fact>
                elif prompt.startswith("/remember"):
                    fact_arg = prompt[9:].strip()
                    print(f"\n{C_ACCENT}✦ Remembering into Local Wiki...{C_RESET}")
                    rem_res = perform_wiki_remember(workspace, fact=fact_arg, messages=messages)
                    print(f"{C_GREEN}✓ {rem_res}{C_RESET}\n")
                    continue

                # 4. /recall <query>
                elif prompt.startswith("/recall"):
                    q = prompt[7:].strip()
                    if q:
                        print(f"\n{C_CYAN}Recalling from Local Wiki for:{C_RESET} {q}\n")
                        print(tool_local_wiki({"action": "search", "query": q}, workspace) + "\n")
                    else:
                        print("Usage: /recall <query>\n")
                    continue

                # 5. Base /wiki commands
                else:
                    sub = prompt[5:].strip()
                    if not wroot:
                        target_folder = workspace
                        if sub.startswith("init"):
                            custom_path = sub[4:].strip()
                            if custom_path:
                                target_folder = Path(custom_path).expanduser().resolve()
                        elif sub and not any(sub.startswith(cmd) for cmd in ("status", "info", "search", "lint", "digest", "env", "help")):
                            cand = Path(sub).expanduser()
                            if cand.is_dir() or cand.parent.is_dir():
                                target_folder = cand.resolve()

                        target_wiki = (target_folder / "wiki" if target_folder.name != "wiki" else target_folder).resolve()
                        print(f"\n{C_ACCENT}✦ Initializing Local Wiki in defined project folder:{C_RESET}")
                        print(f"  {C_BOLD}{target_wiki}{C_RESET}...\n")

                        cmd = ["python3", str(wscript), "init", "--root", str(target_wiki)]
                        try:
                            res = subprocess.run(cmd, cwd=target_folder, capture_output=True, text=True, check=True)
                            print(f"{C_GREEN}✓ Local Wiki ready at {target_wiki}!{C_RESET}")
                            if res.stdout:
                                print(f"{C_MUTED}{res.stdout.strip()}{C_RESET}\n")
                            messages[0] = {"role": "system", "content": build_dl_system_prompt(workspace, mode=current_mode)}
                        except subprocess.CalledProcessError as e:
                            print(f"{C_RED}Failed to initialize wiki: {e.stderr or e.stdout}{C_RESET}\n")
                        continue

                    if not sub or sub in ("status", "info"):
                        print(f"\n{C_BOLD}Local Wiki Status:{C_RESET}")
                        print(f"  • Root:   {C_ACCENT_SOFT}{wroot}{C_RESET}")
                        print(f"  • Script: {wscript}")
                        res = tool_local_wiki({"action": "digest"}, workspace)
                        print(f"\n{res}\n")
                    elif sub.startswith("search"):
                        q = sub[6:].strip()
                        if q:
                            print(f"\n{C_CYAN}Searching Local Wiki for:{C_RESET} {q}\n")
                            print(tool_local_wiki({"action": "search", "query": q}, workspace) + "\n")
                        else:
                            print("Usage: /wiki search <query>\n")
                    elif sub == "lint":
                        print(f"\n{C_CYAN}Linting Local Wiki...{C_RESET}\n")
                        print(perform_wiki_lint(workspace, auto_fix=True) + "\n")
                    elif sub == "backup":
                        print(f"\n{C_ACCENT}✦ Running Local Wiki Artifact Backup...{C_RESET}")
                        print(f"{C_GREEN}✓ {perform_wiki_backup(workspace, messages=messages)}{C_RESET}\n")
                    elif sub.startswith("remember"):
                        fact_arg = sub[8:].strip()
                        print(f"\n{C_ACCENT}✦ Remembering into Local Wiki...{C_RESET}")
                        print(f"{C_GREEN}✓ {perform_wiki_remember(workspace, fact=fact_arg, messages=messages)}{C_RESET}\n")
                    elif sub == "digest":
                        print("\n" + tool_local_wiki({"action": "digest"}, workspace) + "\n")
                    elif sub.startswith("init"):
                        print(f"{C_YELLOW}Local Wiki is already active in this project at: {wroot}{C_RESET}\n")
                    elif sub.startswith("env"):
                        print("\n" + tool_local_wiki({"action": "env_list"}, workspace) + "\n")
                    else:
                        print(f"\n{C_CYAN}Searching Local Wiki for:{C_RESET} {sub}\n")
                        print(tool_local_wiki({"action": "search", "query": sub}, workspace) + "\n")
                    continue
            elif prompt.startswith("/think"):
                print(f"{C_MUTED}/think is gone: the CLI follows the web app's Chat settings "
                      f"({chat_settings_summary(url, api_key)}). Change them under Chat > Settings.{C_RESET}\n")
                continue
            elif prompt.startswith("/search") or prompt.startswith("/exa"):
                if prompt.startswith("/search"):
                    q = prompt[7:].strip()
                else:
                    q = prompt[4:].strip()
                if q:
                    print(f"\n{C_CYAN}Searching Exa AI for:{C_RESET} {q}\n")
                    res = tool_exa_web_search({"query": q})
                    print(res)
                    messages.append({"role": "user", "content": prompt})
                    messages.append({"role": "assistant", "content": res})
                    sync_current_chat_state(messages, workspace)
                else:
                    print("Usage: /exa <query> or /search <query>")
                continue
            elif prompt.startswith("/docs") or prompt.startswith("/context7"):
                if prompt.startswith("/docs"):
                    lib = prompt[5:].strip()
                else:
                    lib = prompt[9:].strip()
                if lib:
                    print(f"\n{C_CYAN}Resolving Context7 docs for:{C_RESET} {lib}\n")
                    res = tool_context7_resolve({"libraryName": lib})
                    print(res)
                    messages.append({"role": "user", "content": prompt})
                    messages.append({"role": "assistant", "content": res})
                    sync_current_chat_state(messages, workspace)
                else:
                    print("Usage: /context7 <library_name> or /docs <library_name>")
                continue
            elif prompt in ("/status", "/model"):
                out = check_status(url, api_key)
                messages.append({"role": "user", "content": prompt})
                messages.append({"role": "assistant", "content": out})
                sync_current_chat_state(messages, workspace)
                continue
            elif prompt in ("/health", "/sys"):
                stats = get_system_health(url, api_key)
                card = format_health_card(stats)
                print(card)
                messages.append({"role": "user", "content": prompt})
                messages.append({"role": "assistant", "content": card})
                sync_current_chat_state(messages, workspace)
                continue
            elif prompt in ("/diff", "/audit"):
                print(f"\n{C_ACCENT}✦ Semantic Git Diff Audit:{C_RESET}")
                diff_res = tool_git_diff_audit({}, workspace)
                print(diff_res + "\n")
                messages.append({"role": "user", "content": prompt})
                messages.append({"role": "assistant", "content": diff_res})
                sync_current_chat_state(messages, workspace)
                continue
            elif prompt.startswith("/secrets") or prompt.startswith("/scan"):
                parts = prompt.split(maxsplit=1)
                sub_path = parts[1].strip() if len(parts) > 1 else ""
                print(f"\n{C_ACCENT}✦ Scanning for Leaked Credentials & Secrets...{C_RESET}")
                args = {"path": sub_path} if sub_path else {}
                print(tool_scan_secrets(args, workspace) + "\n")
                continue
            elif prompt.startswith("/syntax"):
                parts = prompt.split(maxsplit=1)
                sub_path = parts[1].strip() if len(parts) > 1 else ""
                if not sub_path:
                    print("Usage: /syntax <file_path>\n")
                    continue
                print(f"\n{C_ACCENT}✦ Running AST Syntax Guard:{C_RESET}")
                print(tool_syntax_guard({"path": sub_path}, workspace) + "\n")
                continue
            elif prompt.startswith("/test"):
                parts = prompt.split(maxsplit=1)
                sub_files = parts[1].strip() if len(parts) > 1 else ""
                file_list = [f.strip() for f in sub_files.split()] if sub_files else None
                print(f"\n{C_ACCENT}✦ Smart Targeted Test Runner:{C_RESET}")
                args = {"files": file_list} if file_list else {}
                print(tool_smart_test_runner(args, workspace) + "\n")
                continue
            elif prompt.startswith("/save") or prompt.startswith("/export") or prompt.startswith("/markdown"):
                parts = prompt.split(maxsplit=1)
                custom_name = parts[1].strip() if len(parts) > 1 else ""

                user_or_asst = [m for m in messages if m.get("role") in ("user", "assistant")]
                if not user_or_asst:
                    print(f"{C_YELLOW}⚠ No chat messages to export yet.{C_RESET}\n")
                    continue

                now_str = datetime.datetime.now().strftime("%Y-%m-%d-%H-%M")
                if custom_name:
                    out_p = Path(custom_name).expanduser()
                    if not out_p.is_absolute():
                        out_p = (workspace / out_p).resolve()
                    if not out_p.suffix:
                        out_p = out_p.with_suffix(".md")
                else:
                    out_p = workspace / f"dl-ai-code-chat-{now_str}.md"

                md_content = format_messages_to_markdown(messages, model_name="Qwen3.8-Flash-Next Coder", workspace=workspace)
                try:
                    out_p.parent.mkdir(parents=True, exist_ok=True)
                    out_p.write_text(md_content, encoding="utf-8")
                    card_width = 75
                    print(f"\n{C_LINE}╭{'─' * card_width}╮{C_RESET}")
                    print(f"{C_LINE}│{C_RESET}  {C_GREEN}✓ Chat successfully saved as Markdown:{C_RESET}{' ' * (card_width - 40)}{C_LINE}│{C_RESET}")
                    file_str = str(out_p)
                    if len(file_str) > card_width - 8:
                        file_str = "..." + file_str[-(card_width - 11):]
                    print(f"{C_LINE}│{C_RESET}  {C_BOLD}{file_str}{C_RESET}{' ' * (card_width - len(file_str) - 2)}{C_LINE}│{C_RESET}")
                    meta_str = f"Size: {len(md_content):,} bytes · Messages: {len(user_or_asst)}"
                    print(f"{C_LINE}│{C_RESET}  {C_MUTED}{meta_str}{C_RESET}{' ' * (card_width - len(meta_str) - 2)}{C_LINE}│{C_RESET}")
                    print(f"{C_LINE}╰{'─' * card_width}╯{C_RESET}\n")
                except Exception as e:
                    print(f"{C_RED}Error saving chat to {out_p}: {e}{C_RESET}\n")
                continue
            elif prompt.startswith("!"):
                cmd = prompt[1:].strip()
                if cmd:
                    out = _cli().tool_run_command({"CommandLine": cmd}, workspace, interactive=True)   # keeps the tty
                    print(f"\n{out}\n")
                continue

            # File context injection (text inlining and multimodal images)
            messages.append({"role": "user", "content": build_user_message_content(prompt, workspace)})

            # DeepSeek-style Prefix Mode: seed assistant turn with prefix (e.g. ```) to suppress preamble chatter
            if prefix_mode and custom_prefix:
                messages.append({"role": "assistant", "content": custom_prefix, "prefix": True})

            try:
                session_ctx = {"workspace": workspace, "messages": messages, "mode": current_mode, "yolo": yolo,
                               "mcp": mcp, "user_text": prompt, "plan_file": plan_file}
                new_ws = _cli().execute_agent_loop(
                    messages=messages,
                    url=url,
                    api_key=api_key,
                    workspace=workspace,
                    mode=current_mode,
                    session_context=session_ctx,
                )
                plan_file = session_ctx.get("plan_file")
                if new_ws != workspace:
                    workspace = new_ws
                sync_current_chat_state(messages, workspace)
                if current_mode == "plan" and messages and messages[-1].get("role") == "assistant":
                    try:
                        go = input(f"{C_YELLOW}📋 Execute this plan?{C_RESET} [y = execute / Enter = keep planning] ")
                    except (EOFError, KeyboardInterrupt):
                        go = ""
                    if go.strip().lower() in ("y", "yes"):
                        pending_prompt = "/act"
            except Exception as e:
                print(f"{C_RED}Error during agent turn: {e}{C_RESET}\n")
                if messages and messages[-1].get("role") == "user":
                    messages.pop()

    finally:
        if mcp:
            mcp.close()
        try:
            readline.write_history_file(str(history_file))
        except Exception:
            pass
