#!/usr/bin/env python3
"""
deepseek_mcp.py - MCP Server providing DeepSeek Cloud Reasoning to local Strata / D.L. AI / Ray.

Exposes:
- deepseek_reason: DeepSeek-Flash / DeepSeek-V4-Pro with ultra-high thinking reasoning
- deepseek_delegate: Parallel background subagent reasoning query
"""

import os
import sys
import json
from openai import OpenAI

def resolve_api_key():
    """Only the key D.L. AI hands this server (mcp.json env_from_secrets, from ~/.config/dl-ai/secrets.env)."""
    return os.environ.get("DEEPSEEK_API_KEY", "").strip()

def handle_query(prompt: str, model: str = "deepseek-flash", max_tokens: int = 4096) -> str:
    api_key = resolve_api_key()
    if not api_key:
        return "Error: DEEPSEEK_API_KEY is not set in ~/.config/dl-ai/secrets.env."
    
    base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    client = OpenAI(api_key=api_key, base_url=base_url)

    models = [model]
    if model == "deepseek-flash":
        models.append("deepseek-v4-pro")

    for m in models:
        try:
            resp = client.chat.completions.create(
                model=m,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens
            )
            msg = resp.choices[0].message
            out = ""
            if hasattr(msg, "reasoning_content") and msg.reasoning_content:
                out += f"<think>\n{msg.reasoning_content}\n</think>\n\n"
            out += msg.content or ""
            return out
        except Exception as e:
            if m == models[-1]:
                return f"DeepSeek API Error: {e}"

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
                            "model": {"type": "string", "enum": ["deepseek-flash", "deepseek-v4-pro"], "default": "deepseek-flash"}
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
                prompt = args.get("prompt", "")
                model = args.get("model", "deepseek-flash")
                text = handle_query(prompt, model=model)
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
