#!/usr/bin/env python3
"""
europepmc_mcp.py - MCP Server providing Europe PMC scientific literature search to local Strata / D.L. AI / Ray.

Exposes:
- europepmc_search: Search scientific literature across Europe PMC (open-access)
- europepmc_fulltext: Fetch full text for a given PMCID
"""

import sys
import json
import subprocess
from pathlib import Path

WRAPPER = str(Path.home() / ".gemini" / "config" / "plugins" / "science" / "skills" / "literature_search_europepmc" / "scripts" / "europepmc_api.py")

def run_cmd(subcmd: str, arg: str) -> str:
    out_file = "/tmp/epmc_out.json"
    try:
        cmd = ["/usr/bin/uv", "run", WRAPPER, subcmd, arg, "--output", out_file]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        p = Path(out_file)
        if p.is_file():
            content = p.read_text(encoding="utf-8")
            p.unlink(missing_ok=True)
            return content
        return f"Error: No output generated. Stderr: {res.stderr}"
    except Exception as e:
        return f"Europe PMC query error: {e}"

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
                    "serverInfo": {"name": "europepmc-mcp", "version": "1.0.0"}
                }
            }
            _reply(req, res)
        elif method == "tools/list":
            tools = [
                {
                    "name": "europepmc_search",
                    "description": "Search open-access scientific literature on Europe PMC by keyword, query, or DOI.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "The search query, topic, or DOI"}
                        },
                        "required": ["query"]
                    }
                },
                {
                    "name": "europepmc_fulltext",
                    "description": "Retrieve full-text content for a specific PMCID from Europe PMC.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "pmcid": {"type": "string", "description": "The PMCID (e.g. PMC8142387)"}
                        },
                        "required": ["pmcid"]
                    }
                }
            ]
            res = {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": tools}}
            _reply(req, res)
        elif method == "tools/call":
            params = req.get("params", {})
            name = params.get("name")
            args = params.get("arguments", {})
            if name == "europepmc_search":
                q = args.get("query", "")
                text = run_cmd("search", q)
                res = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {"content": [{"type": "text", "text": text}]}
                }
            elif name == "europepmc_fulltext":
                pmcid = args.get("pmcid", "")
                text = run_cmd("get_fulltext", pmcid)
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
