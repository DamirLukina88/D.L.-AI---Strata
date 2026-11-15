"""Status, stall summary, chat export and the saved-chat sync shared by the REPL and the tools.

Moved out of dl_cli.py without changes; see dl_cli.py for the entry point and the names tests patch."""
from __future__ import annotations

from pathlib import Path
from typing import Optional
import datetime
import json
import os
import time
import urllib.request
try:
    from .dl_common import (
    C_ACCENT_SOFT,
    C_BOLD,
    C_GREEN,
    C_RED,
    C_RESET,
    C_YELLOW,
    DEFAULT_API_KEY,
    DEFAULT_URL,
)
except ImportError:
    from dl_common import (
    C_ACCENT_SOFT,
    C_BOLD,
    C_GREEN,
    C_RED,
    C_RESET,
    C_YELLOW,
    DEFAULT_API_KEY,
    DEFAULT_URL,
)
try:
    from .dl_prompt import NOW_PREFIX
except ImportError:
    from dl_prompt import NOW_PREFIX


def chat_settings_summary(url: str = DEFAULT_URL, api_key: str = DEFAULT_API_KEY) -> str:
    """The web app's Chat settings the server applies to this CLI's requests (GET /settings), in one line."""
    try:
        req = urllib.request.Request(f"{url.rstrip('/')}/settings",
                                     headers={"Authorization": f"Bearer {api_key}"} if api_key else {})
        with urllib.request.urlopen(req, timeout=3) as r:
            d = (json.loads(r.read().decode("utf-8")) or {}).get("defaults") or {}
    except urllib.error.HTTPError as e:
        return f"unknown (HTTP {e.code}{': check STRATA_API_KEY' if e.code == 401 else ''})"
    except Exception:
        return "server unreachable"
    if not d:
        return "server defaults (no Chat settings saved yet)"
    parts = [f"effort {d.get('reasoning_effort', 'default')}"]
    temp = d.get("temperature")
    if temp is not None:
        parts.append("greedy" if temp == 0 else f"temp {temp:g}")
    if temp:
        parts += [f"{k} {d[k]:g}" for k in ("top_p", "top_k") if d.get(k) is not None]
    parts.append(f"max {d['max_tokens']}" if d.get("max_tokens") else "max auto")
    if d.get("seed") is not None:
        parts.append(f"seed {d['seed']}")
    return " · ".join(parts)


STALL_LOG = Path(os.environ.get("STRATA_STALL_LOG") or Path.home() / ".local/state/dl-ai/engine-stalls.jsonl")


def stall_summary(day: str | None = None) -> str:
    """Today's fatal verify stalls from the server's log (serve/server.py log_stall): "N today (M with an image)"."""
    day = day or time.strftime("%Y-%m-%d")
    n = img = 0
    try:
        with open(STALL_LOG, encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if str(rec.get("ts", "")).startswith(day):
                    n += 1
                    img += bool(rec.get("image"))
    except OSError:
        pass
    return f"{n} today ({img} with an image)"


def check_status(url: str, api_key: str) -> str:
    endpoint = f"{url.rstrip('/')}/health"
    req = urllib.request.Request(endpoint, headers={"Authorization": f"Bearer {api_key}"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            out = (
                f"\n{C_BOLD}Strata Engine Status:{C_RESET}\n"
                f"  • Status:     {C_GREEN}{data.get('status', 'ok')}{C_RESET}\n"
                f"  • Model:      {C_ACCENT_SOFT}{data.get('model', 'unknown')}{C_RESET}\n"
                f"  • Context:    {data.get('max_context', 0):,} tokens\n"
                f"  • Settings:   {chat_settings_summary(url, api_key)} (the web app's Chat settings)\n"
                f"  • Accelerator: ROCm GPU + Resident RAM\n"
            )
            d = data.get("degraded")
            if isinstance(d, dict):
                out += (f"  • Memory:     {C_YELLOW}started short: {d.get('kept_gib')} of {d.get('wanted_gib')} GiB of "
                        f"experts in RAM, the rest read from disk (slow){C_RESET}\n")
            out += f"  • GPU stalls: {stall_summary()}\n"
            print(out)
            return out.strip()
    except Exception as e:
        err = f"{C_RED}Failed to reach Strata at {url}: {e}{C_RESET}\n"
        print(err)
        return err.strip()


def format_messages_to_markdown(messages: list[dict], model_name: str = "Qwen3.8-Flash-Next Coder",
                                workspace: Optional[Path | str] = None) -> str:
    """Formats chat messages into Markdown matching Strata Web Chat export standard."""
    timestamp_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ws_str = str(workspace) if workspace else os.getcwd()
    header = [
        f"# Strata CLI Chat Export",
        f"- **Date**: {timestamp_str}",
        f"- **Model**: {model_name}",
        f"- **Workspace**: `{ws_str}`",
        "",
        "---",
        ""
    ]

    # Map tool results by tool_call_id
    tool_results: dict[str, dict] = {}
    for m in messages:
        if m.get("role") == "tool":
            t_id = m.get("tool_call_id")
            if t_id:
                tool_results[t_id] = {
                    "name": m.get("name", "tool"),
                    "result": m.get("content", ""),
                }

    sections = []
    for m in messages:
        role = m.get("role")
        if role == "user":
            raw_content = m.get("content", "")
            if isinstance(raw_content, list):
                texts = [p.get("text", "") for p in raw_content if isinstance(p, dict) and p.get("type") == "text"]
                imgs = [p.get("image_url", {}).get("url") if isinstance(p.get("image_url"), dict) else p.get("image_url")
                        for p in raw_content if isinstance(p, dict) and p.get("type") == "image_url"]
                img_desc = " ".join(f"[Image: {img}]" for img in imgs if img)
                text_part = " ".join(texts)
                combined = f"{img_desc}\n{text_part}".strip() if img_desc and img_desc not in text_part else text_part
                content = NOW_PREFIX.sub("", combined).strip()
            else:
                content = NOW_PREFIX.sub("", str(raw_content or "")).strip()
            if content:
                sections.append(f"## You\n\n{content}\n")
        elif role == "assistant":
            parts = [f"## {model_name}\n"]
            # Collapsible thinking block
            reasoning = m.get("reasoning_content") or m.get("reasoning")
            if reasoning and str(reasoning).strip():
                parts.append(f"<details><summary>Thinking</summary>\n\n{str(reasoning).strip()}\n\n</details>\n")

            # Collapsible tool calls and outputs
            tool_calls = m.get("tool_calls") or []
            for tc in tool_calls:
                t_id = tc.get("id")
                fn = tc.get("function", {})
                name = fn.get("name", "tool")
                raw_args = fn.get("arguments", "{}")
                try:
                    args_obj = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    args_formatted = json.dumps(args_obj, indent=2)
                except Exception:
                    args_formatted = str(raw_args)

                res_obj = tool_results.get(t_id, {})
                res_text = res_obj.get("result", "")

                parts.append(
                    f"<details><summary>Tool {name}</summary>\n\n"
                    f"```json\n{args_formatted}\n```\n\n"
                    f"```\n{res_text}\n```\n\n"
                    f"</details>\n"
                )

            # Assistant content text
            text = m.get("content") or ""
            if text and str(text).strip():
                parts.append(f"{str(text).strip()}\n")

            if len(parts) > 1 or (len(parts) == 1 and text and str(text).strip()):
                sections.append("\n".join(parts))

    return "\n".join(header) + "\n" + "\n".join(sections)


def sync_current_chat_state(messages: list[dict], workspace: Path, model_name: str = "Qwen3.8-Flash-Next Coder"):
    """Persists active session state to /tmp/dl-cli-current-chat.json for Web Code export."""
    try:
        state_file = Path("/tmp/dl-cli-current-chat.json")
        data = {
            "model": model_name,
            "workspace": str(workspace),
            "updated_at": time.time(),
            "messages": messages,
        }
        state_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass
