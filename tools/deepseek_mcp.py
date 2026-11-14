#!/usr/bin/env python3
"""
deepseek_mcp.py - MCP Server providing DeepSeek Cloud Reasoning to local Strata / D.L. AI / Ray.

Exposes:
- deepseek_reason: the newest DeepSeek Flash model (falling back step by step to older ones), optional web search
- deepseek_delegate: Parallel background subagent reasoning query
"""

import os
import sys
import json
from openai import OpenAI

def resolve_api_key():
    """Only the key D.L. AI hands this server (mcp.json env_from_secrets, from ~/.config/dl-ai/secrets.env)."""
    return os.environ.get("DEEPSEEK_API_KEY", "").strip()

# Model choice (2026-11-14): the newest Flash model the account lists, then older ones, step by step, so an outage or a
# retired id never ends the call.  The /models list is cached for a day; without it the built-in ladder is used.
LADDER = ["deepseek-flash", "deepseek-v4-pro", "deepseek-chat"]
MODEL_CACHE = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "dl-ai",
                           "deepseek-models.json")
WEB_TOOLS = [{"type": "deepseek_web_search"}, {"type": "deepseek_read_url"}]


def _version_key(mid: str):
    """Newest first: higher version numbers and later date suffixes sort first ('deepseek-v4.1-flash-1017' over
    'deepseek-v4-flash'); the plain alias 'deepseek-flash' after dated ids of the same family."""
    import re
    nums = [int(n) for n in re.findall(r"\d+", mid)]
    return (nums or [0]) + [0] * (6 - len(nums))


def model_ladder(client, wanted: str = "auto") -> list:
    """The models to try in order.  'auto' (or a Flash name): every Flash model the account lists, newest first, then
    the alias deepseek-flash, then deepseek-v4-pro and deepseek-chat.  Another name: that one, then the ladder."""
    import time
    listed = []
    try:
        st = os.stat(MODEL_CACHE)
        if time.time() - st.st_mtime < 86400:
            listed = json.load(open(MODEL_CACHE))
    except (OSError, ValueError):
        pass
    if not listed:
        try:
            listed = sorted(m.id for m in client.models.list().data)
            os.makedirs(os.path.dirname(MODEL_CACHE), exist_ok=True)
            json.dump(listed, open(MODEL_CACHE, "w"))
        except Exception:
            listed = []
    flash = sorted((m for m in listed if "flash" in m.lower()), key=_version_key, reverse=True)
    out = []
    if wanted and wanted not in ("auto", "deepseek-flash"):
        out.append(wanted)
    for m in flash + LADDER:
        if m not in out and (not listed or m in listed):     # only models the account offers, once it is known
            out.append(m)
    return out


def _retry_with_next(err: Exception) -> bool:
    """Availability problems step down to the next model; a bad key or an empty balance does not (no model helps)."""
    code = getattr(err, "status_code", None)
    text = str(err).lower()
    if code in (401, 402, 403) or "insufficient balance" in text or "authentication" in text:
        return False
    return True


def handle_query(prompt: str, model: str = "auto", max_tokens: int = 8192, system: str = "",
                 web: bool = False, include_thinking: bool = True, timeout: float = 300) -> str:
    api_key = resolve_api_key()
    if not api_key:
        return "Error: DEEPSEEK_API_KEY is not set in ~/.config/dl-ai/secrets.env."

    base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
    messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
    extra = {"thinking": {"type": "enabled"}}
    if web:
        extra["tools"] = WEB_TOOLS
    tried = []
    for m in model_ladder(client, model):
        try:
            resp = client.chat.completions.create(model=m, messages=messages, max_tokens=max_tokens,
                                                  extra_body=extra)
            msg = resp.choices[0].message
            content = (msg.content or "").strip()
            if not content:
                raise RuntimeError("empty reply")
            out = ""
            if include_thinking and getattr(msg, "reasoning_content", None):
                out += f"<think>\n{msg.reasoning_content}\n</think>\n\n"
            out += content
            note = f"\n\n[model: {m}" + (f"; after {', '.join(tried)} failed" if tried else "") + "]"
            return out + note
        except Exception as e:
            tried.append(f"{m} ({str(e)[:80]})")
            if not _retry_with_next(e):
                return f"DeepSeek API Error: {e}"
    return "DeepSeek API Error: every model failed: " + "; ".join(tried)

def _reply(req, res):
    """Write one JSON-RPC reply: nothing for a notification, an empty result for ping, and isError on a tool
    result whose text is an error message ("... error: ...")."""
    if "id" not in req:
        return
    if req.get("method") == "ping":
        res = {"jsonrpc": "2.0", "id": req["id"], "result": {}}
    result = res.get("result")
    if req.get("method") == "tools/call" and isinstance(result, dict) and "isError" not in result:
        text = "".join(c.get("text", "") for c in result.get("content", []) if isinstance(c, dict))
        head = text.lstrip().split(":", 1)
        result["isError"] = len(head) == 2 and len(head[0]) <= 45 and any(
            w in head[0].lower() for w in ("error", "failed"))
    sys.stdout.write(json.dumps(res) + "\n")
    sys.stdout.flush()


def main():
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        try:
            req = json.loads(line)
        except Exception:
            continue

        method = req.get("method")
        msg_id = req.get("id")

        if method == "initialize":
            res = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "deepseek-mcp", "version": "1.0.0"}
                }
            }
            _reply(req, res)
        elif method == "tools/list":
            tools = [
                {
                    "name": "deepseek_reason",
                    "description": "Query DeepSeek cloud reasoning with ultra-high thinking effort (deep mathematical proofs, scientific deduction, and second opinions).",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "prompt": {"type": "string", "description": "The reasoning or analysis task for DeepSeek."},
                            "model": {"type": "string", "default": "auto",
                                      "description": "auto (default): the newest Flash model, stepping down to older ones if it is unavailable; or a model id"},
                            "system": {"type": "string", "description": "Optional system prompt."},
                            "web": {"type": "boolean", "default": False,
                                    "description": "Let DeepSeek search the web and read URLs (billed per search/fetch)."},
                            "include_thinking": {"type": "boolean", "default": True,
                                                 "description": "Prepend DeepSeek's reasoning in <think> tags."}
                        },
                        "required": ["prompt"]
                    }
                }
            ]
            res = {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": tools}}
            _reply(req, res)
        elif method == "tools/call":
            params = req.get("params", {})
            name = params.get("name")
            args = params.get("arguments", {})
            if name == "deepseek_reason":
                text = handle_query(args.get("prompt", ""), model=args.get("model") or "auto",
                                    system=args.get("system") or "", web=bool(args.get("web")),
                                    include_thinking=args.get("include_thinking", True) is not False)
                res = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {"content": [{"type": "text", "text": text}]}
                }
            else:
                res = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {"code": -32601, "message": f"Method not found: {name}"}
                }
            _reply(req, res)
        else:
            _reply(req, {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": "Method not found"}})

if __name__ == "__main__":
    main()
