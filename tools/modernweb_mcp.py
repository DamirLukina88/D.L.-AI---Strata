#!/usr/bin/env python3
"""modernweb_mcp.py - Free Modern Web Guidance standards MCP server via npx modern-web-guidance."""
import sys
import json
import subprocess

def search_guidance(query: str) -> str:
    try:
        cmd = ["npx", "-y", "modern-web-guidance@latest", "search", query]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        raw = res.stdout.strip()
        lines = [l for l in raw.splitlines() if not l.startswith("npm notice")]
        clean_json = "\n".join(lines).strip()
        data = json.loads(clean_json)
        if not data:
            return f"No modern web patterns found for: {query}"
        
        out = [f"Found {len(data)} modern web standards/guides for '{query}':\n"]
        for item in data[:4]:
            gid = item.get("id")
            desc = item.get("description", "")
            cat = item.get("category", "")
            feats = ", ".join(item.get("featuresUsed", []))
            out.append(f"### `{gid}` ({cat})\n- **Summary:** {desc}\n" + (f"- **Features:** {feats}\n" if feats else ""))
        out.append("\n*Tip: Use `modern_web_retrieve` with the guide ID to fetch the full best-practice implementation.*")
        return "\n".join(out)
    except Exception as e:
        return f"Modern Web Guidance error: {e}"

def retrieve_guidance(guide_id: str) -> str:
    try:
        cmd = ["npx", "-y", "modern-web-guidance@latest", "retrieve", guide_id]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        raw = res.stdout.strip()
        lines = [l for l in raw.splitlines() if not l.startswith("npm notice")]
        text = "\n".join(lines).strip()
        if not text:
            return f"No guide content found for ID: {guide_id}"
        return text[:4500] + ("\n\n*(Truncated to first 4,500 chars)*" if len(text) > 4500 else "")
    except Exception as e:
        return f"Modern Web Guidance retrieve error: {e}"

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
            res = {"jsonrpc": "2.0", "id": mid, "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "modernweb-mcp", "version": "1.0.0"}}}
        elif m == "tools/list":
            tools = [
                {
                    "name": "modern_web_search",
                    "description": "Search current web platform standards (HTML5, CSS layout, anchor positioning, view transitions, responsive UI) via Modern Web Guidance.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Web capability or pattern, e.g. 'responsive table', 'dialog backdrop', 'container queries'"}
                        },
                        "required": ["query"]
                    }
                },
                {
                    "name": "modern_web_retrieve",
                    "description": "Retrieve full best-practice code guide for a specific guide ID from Modern Web Guidance.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "guide_id": {"type": "string", "description": "The guide ID, e.g. 'html', 'css-layout', 'accessibility'"}
                        },
                        "required": ["guide_id"]
                    }
                }
            ]
            res = {"jsonrpc": "2.0", "id": mid, "result": {"tools": tools}}
        elif m == "tools/call":
            params = req.get("params", {})
            name = params.get("name")
            args = params.get("arguments", {})
            if name == "modern_web_search":
                text = search_guidance(args.get("query", ""))
            elif name == "modern_web_retrieve":
                text = retrieve_guidance(args.get("guide_id", ""))
            else:
                text = f"Unknown tool: {name}"
            res = {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": text}]}}
        else:
            res = {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "Method not found"}}
        _reply(req, res)

if __name__ == "__main__":
    main()
