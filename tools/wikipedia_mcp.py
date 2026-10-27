#!/usr/bin/env python3
"""wikipedia_mcp.py - Free Wikipedia REST API MCP server."""
import sys
import json
import urllib.request
import urllib.parse

def wiki_summary(title: str) -> str:
    try:
        encoded = urllib.parse.quote(title.strip().replace(" ", "_"))
        url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{encoded}"
        req = urllib.request.Request(url, headers={"User-Agent": "DL-AI-Strata/1.0 (+https://github.com/DamirLukina88/D.L.-AI---Strata)"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode("utf-8"))
        
        t = data.get("title", title)
        desc = data.get("description", "")
        extract = data.get("extract", "No extract available.")
        page_url = data.get("content_urls", {}).get("desktop", {}).get("page", "")
        return f"## {t}\n*{desc}*\n\n{extract}\n\n**Source:** {page_url}"
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return f"Wikipedia article '{title}' not found."
        return f"Wikipedia HTTP Error: {e}"
    except Exception as e:
        return f"Wikipedia API error: {e}"

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
            res = {"jsonrpc": "2.0", "id": mid, "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "wikipedia-mcp", "version": "1.0.0"}}}
        elif m == "tools/list":
            tools = [{
                "name": "wikipedia_lookup",
                "description": "Look up factual summaries, historical overviews, concepts, and biographies on Wikipedia.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "topic": {"type": "string", "description": "The topic, term, or entity name to look up"}
                    },
                    "required": ["topic"]
                }
            }]
            res = {"jsonrpc": "2.0", "id": mid, "result": {"tools": tools}}
        elif m == "tools/call":
            params = req.get("params", {})
            args = params.get("arguments", {})
            text = wiki_summary(args.get("topic", ""))
            res = {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": text}]}}
        else:
            res = {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "Method not found"}}
        _reply(req, res)

if __name__ == "__main__":
    main()
