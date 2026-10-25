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
from pathlib import Path
from openai import OpenAI

def resolve_api_key():
    key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if key and key.startswith("sk-"):
        return key
    
    env_paths = [
        Path.home() / "Desktop" / "Strata" / "wiki" / "private" / ".env",
        Path.home() / ".config" / "dl-ai" / "secrets.env"
    ]
    for p in env_paths:
        if p.is_file():
            try:
                for line in p.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line.startswith("DEEPSEEK_API_KEY="):
                        val = line.split("=", 1)[1].strip().strip('"').strip("'")
                        if val:
                            return val
            except Exception:
                pass
    return key

def handle_query(prompt: str, model: str = "deepseek-flash", max_tokens: int = 4096) -> str:
    api_key = resolve_api_key()
    if not api_key:
        return "Error: No DeepSeek API key configured in secrets.env or wiki/private/.env."
    
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
            sys.stdout.write(json.dumps(res) + "\n")
            sys.stdout.flush()
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
            sys.stdout.write(json.dumps(res) + "\n")
            sys.stdout.flush()
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
            sys.stdout.write(json.dumps(res) + "\n")
            sys.stdout.flush()

if __name__ == "__main__":
    main()
