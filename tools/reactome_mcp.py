#!/usr/bin/env python3
"""reactome_mcp.py - Free Reactome biological pathways database MCP server."""
import sys
import json
import urllib.request
import urllib.parse
import re

def search_pathways(query: str, species: str = "Homo sapiens") -> str:
    try:
        encoded = urllib.parse.quote(query)
        sp_enc = urllib.parse.quote(species)
        url = f"https://reactome.org/ContentService/search/query?query={encoded}&species={sp_enc}&types=Pathway"
        req = urllib.request.Request(url, headers={"User-Agent": "DL-AI-Strata/1.0"})
        with urllib.request.urlopen(req, timeout=12) as r:
            data = json.loads(r.read().decode("utf-8"))
        
        results = data.get("results", [])
        entries = []
        for r in results:
            entries.extend(r.get("entries", []))
        
        if not entries:
            return f"No Reactome pathways found for query: '{query}' in species '{species}'."
        
        lines = [f"Found {len(entries)} Reactome pathway(s) for '{query}':\n"]
        for e in entries[:5]:
            raw_name = e.get("name", "Unnamed")
            clean_name = re.sub(r"<[^>]+>", "", raw_name)
            stId = e.get("stId", "N/A")
            summary = re.sub(r"<[^>]+>", "", e.get("summation", "No summary available"))
            diagram_url = f"https://reactome.org/PathwayBrowser/#/{stId}"
            lines.append(f"### [{stId}] {clean_name}\n- **Summary:** {summary[:300]}...\n- **Pathway Diagram:** {diagram_url}\n")
        return "\n".join(lines)
    except Exception as e:
        return f"Reactome API error: {e}"

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
            res = {"jsonrpc": "2.0", "id": mid, "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "reactome-mcp", "version": "1.0.0"}}}
        elif m == "tools/list":
            tools = [{
                "name": "reactome_search",
                "description": "Search biological pathways, cellular cascades, and metabolic reactions in Reactome.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Pathway name, metabolic process, or signaling cascade (e.g. glycolysis, apoptosis, EGFR signaling)"},
                        "species": {"type": "string", "default": "Homo sapiens"}
                    },
                    "required": ["query"]
                }
            }]
            res = {"jsonrpc": "2.0", "id": mid, "result": {"tools": tools}}
        elif m == "tools/call":
            params = req.get("params", {})
            args = params.get("arguments", {})
            text = search_pathways(args.get("query", ""), args.get("species", "Homo sapiens"))
            res = {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": text}]}}
        else:
            res = {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "Method not found"}}
        _reply(req, res)

if __name__ == "__main__":
    main()
