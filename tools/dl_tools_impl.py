"""The core tools: files, commands, web search, library docs, and the MCP built-ins registered at import.

Moved out of dl_cli.py without changes; see dl_cli.py for the entry point and the names tests patch."""
from __future__ import annotations

from pathlib import Path
import json
import os
import signal
import subprocess
import tempfile
import time
import urllib.request
try:
    from .dl_boundary import _listeners
except ImportError:
    from dl_boundary import _listeners
try:
    from .dl_common import (
    DEFAULT_CLIENT_IP_KEY,
    DEFAULT_CONTEXT7_KEY,
    DEFAULT_EXA_KEY,
    dl_mcp,
    dl_memory,
    memory_store,
    scan_secrets_in_text,
    validate_syntax,
)
except ImportError:
    from dl_common import (
    DEFAULT_CLIENT_IP_KEY,
    DEFAULT_CONTEXT7_KEY,
    DEFAULT_EXA_KEY,
    dl_mcp,
    dl_memory,
    memory_store,
    scan_secrets_in_text,
    validate_syntax,
)
try:
    from .dl_context import STAND_IN
except ImportError:
    from dl_context import STAND_IN
try:
    from .dl_media import IMAGE_EXTENSIONS
except ImportError:
    from dl_media import IMAGE_EXTENSIONS
try:
    from .dl_prompt import build_dl_system_prompt
except ImportError:
    from dl_prompt import build_dl_system_prompt
try:
    from .dl_status import sync_current_chat_state
except ImportError:
    from dl_status import sync_current_chat_state
try:
    from .dl_tools_schema import DL_TOOLS, resolve_wiki_root
except ImportError:
    from dl_tools_schema import DL_TOOLS, resolve_wiki_root


# Tool implementations
def tool_view_file(args: dict, workspace: Path) -> str:
    path_str = args.get("AbsolutePath") or args.get("path")
    if not path_str:
        return "Error: AbsolutePath required"
    p = Path(path_str).expanduser()
    if not p.is_absolute():
        p = (workspace / p).resolve()
    if not p.is_file():
        return f"Error: File not found: {p}"
    # an image is shown to the model as an image (tool_result_images), not read as text (that gave raw JPEG bytes)
    if p.suffix.lower() in IMAGE_EXTENSIONS:
        return f"Image file {p} ({p.stat().st_size // 1024} KB): shown to you as an image. [[image: {p}]]"
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        start = args.get("StartLine", 1) or 1
        end = args.get("EndLine", len(lines)) or len(lines)
        start = max(1, min(start, len(lines)))
        end = max(start, min(end, len(lines)))
        selected = lines[start - 1 : end]
        numbered = [f"{i}: {line}" for i, line in enumerate(selected, start=start)]
        return f"File: {p} (lines {start}-{end} of {len(lines)})\n" + "\n".join(numbered)
    except Exception as e:
        return f"Error reading file {p}: {e}"


def tool_switch_workspace(args: dict, workspace: Path, session_context: dict | None = None) -> str:
    path_str = (args.get("path") or args.get("workspace") or "").strip()
    if not path_str:
        return "Error: path required"
    new_path = Path(path_str).expanduser()
    if not new_path.is_absolute():
        new_path = (workspace / new_path).resolve()
    else:
        new_path = new_path.resolve()

    if not new_path.exists():
        try:
            new_path.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            return f"Error creating target directory {new_path}: {e}"

    if not new_path.is_dir():
        return f"Error: Path {new_path} is not a directory"

    try:
        os.chdir(new_path)
    except Exception as e:
        return f"Error changing working directory to {new_path}: {e}"

    # Update session context state if provided
    wroot = resolve_wiki_root(new_path)
    if session_context is not None:
        session_context["workspace"] = new_path
        messages = session_context.get("messages")
        mode = session_context.get("mode", "act")
        if messages and len(messages) > 0 and messages[0].get("role") == "system":
            messages[0]["content"] = build_dl_system_prompt(new_path, mode=mode)
        sync_current_chat_state(messages, new_path)

    store = memory_store()
    if store:
        wiki_status = f"Memory: project `{dl_memory.resolve_project_slug(new_path, store)}` in {store} (global rules apply too)"
    else:
        wiki_status = f"Local Wiki active ({wroot})" if wroot else "Local Wiki inactive (call local_wiki(action='init') to initialize in this directory)"
    return f"Working directory successfully switched to: {new_path}\n{wiki_status}"


def stand_in_error(new_text: str, old_text: str, what: str) -> str:
    """An error when new_text holds more trim stand-ins (STAND_IN) than the file had: the model copied one out of
    its trimmed history (CONTRA, 2026-10-20: 33 times in 6 h; twice it overwrote a 14k test file with one). A file
    that already holds stand-ins can still be edited, and an edit that replaces one with real text is a repair."""
    added = len(STAND_IN.findall(new_text)) - len(STAND_IN.findall(old_text))
    if added <= 0:
        return ""
    return (f"Error [stand_in_guard]: {what} blocked: the new text holds {added} trim stand-in(s) like "
            f"\"{STAND_IN.search(new_text).group(0)[:60]}...\". D.L. CLI puts that line where it trimmed old text "
            "out of the conversation; it is not file content. view_file the file (or the source you are copying "
            "from) and send the real text.")


def tool_write_to_file(args: dict, workspace: Path) -> str:
    path_str = args.get("TargetFile") or args.get("path")
    if not path_str:
        return "Error: TargetFile required"
    p = Path(path_str).expanduser()
    if not p.is_absolute():
        p = (workspace / p).resolve()
    overwrite = args.get("Overwrite", True)
    if p.exists() and not overwrite:
        return f"Error: File {p} already exists and Overwrite is False"
    content = args.get("CodeContent") or args.get("content") or ""

    try:
        old = p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""
    except OSError:
        old = ""
    err = stand_in_error(content, old, "Write")
    if err:
        return err

    # Pre-write Guardrail 1: scan_secrets
    is_clean, sec_err = scan_secrets_in_text(content, p)
    if not is_clean:
        return f"SECURITY ERROR [scan_secrets]: Write blocked to prevent secret leak:\n{sec_err}\nPlease remove or redact credentials/tokens before writing."

    # Pre-write Guardrail 2: syntax_guard
    is_valid, syn_err = validate_syntax(content, p)
    if not is_valid:
        return f"SYNTAX ERROR [syntax_guard]: Write blocked due to invalid syntax:\n{syn_err}\nPlease fix the syntax error and try again."

    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Successfully wrote {len(content)} characters to {p}"
    except Exception as e:
        return f"Error writing file {p}: {e}"


def tool_replace_file_content(args: dict, workspace: Path) -> str:
    path_str = args.get("TargetFile") or args.get("path")
    if not path_str:
        return "Error: TargetFile required"
    p = Path(path_str).expanduser()
    if not p.is_absolute():
        p = (workspace / p).resolve()
    if not p.is_file():
        return f"Error: File not found: {p}"
    target = args.get("TargetContent", "")
    replacement = args.get("ReplacementContent", "")
    try:
        orig = p.read_text(encoding="utf-8", errors="replace")
        if target not in orig:
            if STAND_IN.search(target):
                return (f"Error: TargetContent not found in {p}: it holds a trim stand-in "
                        f"(\"{STAND_IN.search(target).group(0)[:60]}...\"), not the file's text. view_file the "
                        "lines you want to change and copy them exactly.")
            return f"Error: TargetContent not found in {p}"
        new_text = orig.replace(target, replacement, 1)
        err = stand_in_error(new_text, orig, "File modification")
        if err:
            return err

        # Pre-write Guardrail 1: scan_secrets
        is_clean, sec_err = scan_secrets_in_text(new_text, p)
        if not is_clean:
            return f"SECURITY ERROR [scan_secrets]: File modification blocked to prevent secret leak:\n{sec_err}\nPlease remove or redact credentials/tokens before saving."

        # Pre-write Guardrail 2: syntax_guard
        is_valid, syn_err = validate_syntax(new_text, p)
        if not is_valid:
            return f"SYNTAX ERROR [syntax_guard]: File modification blocked due to invalid syntax:\n{syn_err}\nPlease fix the syntax error and try again."

        p.write_text(new_text, encoding="utf-8")
        return f"Successfully updated {p}"
    except Exception as e:
        return f"Error updating file {p}: {e}"


RUN_COMMAND_TIMEOUT_S = 120.0


def tool_run_command(args: dict, workspace: Path) -> str:
    cmd = args.get("CommandLine") or args.get("command")
    if not cmd:
        return "Error: CommandLine required"
    cwd_str = args.get("Cwd")
    # relative to the workspace (as the approval gate reads it), not to this process's folder
    cwd = (workspace / Path(str(cwd_str)).expanduser()).resolve() if cwd_str else workspace
    # Output goes to files, not pipes: a child left running in the background (`server &` without a redirect)
    # kept a pipe open, so the call waited the whole timeout and returned no output.  Its own session, so a
    # timeout ends the whole group (`a && b`, pipelines), not only the shell; what was printed is kept.
    try:
        with tempfile.TemporaryFile() as fo, tempfile.TemporaryFile() as fe:
            proc = subprocess.Popen(str(cmd), shell=True, cwd=cwd, stdin=subprocess.DEVNULL, stdout=fo, stderr=fe,
                                    start_new_session=True)
            try:
                code = proc.wait(timeout=RUN_COMMAND_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(proc.pid, signal.SIGKILL) if hasattr(os, "killpg") else proc.kill()
                except OSError:
                    pass
                proc.wait()
                code = None
            fo.seek(0)
            fe.seek(0)
            stdout = fo.read().decode("utf-8", errors="replace")
            stderr = fe.read().decode("utf-8", errors="replace")
        out = []
        if stdout:
            out.append(stdout)
        if stderr:
            out.append(f"Stderr:\n{stderr}")
        out.append(f"[Command exited with code {code}]" if code is not None
                   else f"Error: Command timed out after {RUN_COMMAND_TIMEOUT_S:.0f}s (ended; its output so far is above)")
        return "\n".join(out).strip()
    except Exception as e:
        return f"Error running command: {e}"


def _note_new_listeners(bg: list, before: dict, t0: float, wait_s: float = 1.5) -> None:
    """Adds to bg the ports that processes started since t0 began listening on (a server needs a moment to bind)."""
    import psutil
    end = time.time() + wait_s
    while True:
        new = {k: v for k, v in _listeners().items()
               if k not in before and v >= t0 - 1 and k[0] not in (os.getpid(), os.getppid())}
        if new or time.time() >= end:
            break
        time.sleep(0.25)
    known = {(p, port) for p, port, _, _ in bg}
    for (pid, port), started in new.items():
        if (pid, port) in known:
            continue
        try:
            name = psutil.Process(pid).name()
        except psutil.Error:
            name = "background"
        bg.append((pid, port, started, name))


def tool_exa_web_search(args: dict) -> str:
    query = args.get("query")
    if not query:
        return "Error: query required"
    try:
        num_results = max(1, min(int(args.get("num_results", 5) or 5), 10))
    except (TypeError, ValueError):     # "five" or a list from the model
        num_results = 5
    api_key = DEFAULT_EXA_KEY
    if not api_key:
        return "Error: EXA_API_KEY is not set (add it to ~/.config/dl-ai/secrets.env)"
    url = "https://api.exa.ai/search"
    headers = {
        "x-api-key": api_key,
        "Content-Type": "application/json"
    }
    payload = {
        "query": query,
        "numResults": num_results,
        "useAutoprompt": True,
        "contents": {
            "text": {"maxCharacters": 800}
        }
    }
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            results = data.get("results") or []
            if not results:
                return f"No search results found for: '{query}'"
            out = [f"Exa Web Search results for: '{query}'\n"]
            for i, r in enumerate(results, 1):
                title = r.get("title") or "Untitled"
                link = r.get("url") or ""
                text = (r.get("text") or "").strip()
                out.append(f"[{i}] {title}\nURL: {link}\nSummary: {text}\n")
            return "\n".join(out)
    except Exception as e:
        return f"Error searching Exa: {e}"


def call_context7_mcp_raw(tool_name: str, arguments: dict) -> str:
    env = {
        **{k: os.environ[k] for k in ("HOME", "USER", "LANG", "TMPDIR", "XDG_CACHE_HOME") if k in os.environ},
        "CONTEXT7_API_KEY": DEFAULT_CONTEXT7_KEY,
        "CLIENT_IP_ENCRYPTION_KEY": DEFAULT_CLIENT_IP_KEY,
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:" + os.environ.get("PATH", "")
    }
    try:
        proc = subprocess.Popen(
            ["/usr/bin/npx", "@upstash/context7-mcp@1.0.31"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env
        )
        init_req = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "dl-cli", "version": "1.0"}
            }
        }
        proc.stdin.write(json.dumps(init_req) + "\n")
        proc.stdin.flush()

        call_req = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments
            }
        }
        proc.stdin.write(json.dumps(call_req) + "\n")
        proc.stdin.flush()

        result_text = ""
        for line in proc.stdout:
            try:
                res = json.loads(line)
                if res.get("id") == 2:
                    content_items = (res.get("result") or {}).get("content") or []
                    texts = [item.get("text", "") for item in content_items if item.get("type") == "text"]
                    result_text = "\n".join(texts)
                    break
            except Exception:
                continue

        proc.terminate()
        return result_text.strip() or "No documentation content returned by Context7."
    except Exception as e:
        return f"Error calling Context7 MCP: {e}"


def tool_context7_resolve(args: dict) -> str:
    lib = args.get("libraryName")
    if not lib:
        return "Error: libraryName required"
    return call_context7_mcp_raw("resolve-library-id", {"libraryName": lib})


def tool_context7_docs(args: dict) -> str:
    lib_id = args.get("context7CompatibleLibraryID")
    if not lib_id:
        return "Error: context7CompatibleLibraryID required"
    payload = {"context7CompatibleLibraryID": lib_id}
    if args.get("topic"):
        payload["topic"] = args["topic"]
    if args.get("mode"):
        payload["mode"] = args["mode"]
    return call_context7_mcp_raw("get-library-docs", payload)


if dl_mcp is not None:
    # mcp.json can load Exa on demand ({"builtin": "exa"}) instead of offering it with every turn
    _exa = next(t for t in DL_TOOLS if t["function"]["name"] == "exa_web_search")["function"]
    dl_mcp.register_builtin("exa", [{"name": "web_search", "description": _exa["description"],
                                     "inputSchema": _exa["parameters"]}],
                            lambda tool, args: tool_exa_web_search(args))
    # Proton Mail through the local Proton Mail Bridge ({"builtin": "proton"}), standard library only
    try:
        try:
            from tools import dl_proton
        except ImportError:
            import dl_proton
        dl_mcp.register_builtin("proton", dl_proton.TOOLS, dl_proton.call)
    except ImportError:
        pass
    # DeepL for whole texts, HTML and files ({"builtin": "deepl"}), standard library only
    try:
        try:
            from tools import dl_translate
        except ImportError:
            import dl_translate
        dl_mcp.register_builtin("deepl", dl_translate.TOOLS, dl_translate.call)
    except ImportError:
        pass
    # scheduled jobs ({"builtin": "schedule"}); the session daemon runs them
    try:
        try:
            from tools import dl_schedule
        except ImportError:
            import dl_schedule
        dl_mcp.register_builtin("schedule", dl_schedule.TOOLS, dl_schedule.call)
    except ImportError:
        pass
