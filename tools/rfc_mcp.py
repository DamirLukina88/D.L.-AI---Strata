#!/usr/bin/env python3
"""rfc_mcp.py - Free IETF RFC internet standards MCP server."""
import sys
import json
import urllib.request
import re

def fetch_rfc(rfc_num: str) -> str:
    try:
        num = re.sub(r"[^\d]", "", str(rfc_num))
        if not num:
            return "Please provide a valid RFC number, e.g. 9110 or 'RFC 7540'."
        url = f"https://www.rfc-editor.org/rfc/rfc{num}.txt"
        req = urllib.request.Request(url, headers={"User-Agent": "DL-AI-Strata/1.0"})
        with urllib.request.urlopen(req, timeout=12) as r:
            text = r.read(8000).decode("utf-8", errors="ignore")
        
        url_doc = f"https://datatracker.ietf.org/doc/html/rfc{num}"
        return f"## IETF RFC {num}\n**Official Spec:** {url_doc}\n\n```text\n{text[:3500]}\n...\n```\n*(Text truncated to first 3,500 characters. View full specification at {url_doc})*"
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return f"RFC {rfc_num} not found."
        return f"RFC HTTP Error: {e}"
    except Exception as e:
        return f"RFC fetch error: {e}"

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
        m, mid = req.get("method"), req.get("id")
        if m == "initialize":
            res = {"jsonrpc": "2.0", "id": mid, "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "rfc-mcp", "version": "1.0.0"}}}
        elif m == "tools/list":
            tools = [{
                "name": "rfc_lookup",
                "description": "Fetch official IETF RFC protocol standards and internet specifications (e.g. HTTP, WebSockets, TLS).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "number": {"type": "string", "description": "RFC number, e.g. 9110, 7540, 6455"}
                    },
                    "required": ["number"]
                }
            }]
            res = {"jsonrpc": "2.0", "id": mid, "result": {"tools": tools}}
        elif m == "tools/call":
            params = req.get("params", {})
            args = params.get("arguments", {})
            text = fetch_rfc(args.get("number", ""))
            res = {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": text}]}}
        else:
            res = {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "Method not found"}}
        _reply(req, res)

if __name__ == "__main__":
    main()
