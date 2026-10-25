#!/usr/bin/env python3
"""openalex_mcp.py - Free OpenAlex global academic literature graph MCP server."""
import sys
import json
import urllib.request
import urllib.parse

def search_openalex(query: str, per_page: int = 5) -> str:
    try:
        encoded = urllib.parse.quote(query)
        url = f"https://api.openalex.org/works?search={encoded}&per-page={per_page}"
        req = urllib.request.Request(url, headers={"User-Agent": "DL-AI-Strata/1.0 (mailto:info@damir-lukina.com)"})
        with urllib.request.urlopen(req, timeout=12) as r:
            data = json.loads(r.read().decode("utf-8"))
        
        results = data.get("results", [])
        if not results:
            return f"No scholarly works found on OpenAlex for: {query}"
        
        out = []
        for w in results:
            title = w.get("display_name", "Untitled")
            pub_year = w.get("publication_year", "N/A")
            cites = w.get("cited_by_count", 0)
            doi = w.get("doi", "")
            authors = [a.get("author", {}).get("display_name", "") for a in w.get("authorships", [])]
            venue = w.get("primary_location", {}).get("source", {}).get("display_name", "") or "Independent"
            landing_url = w.get("primary_location", {}).get("landing_page_url", "") or doi
            out.append(f"### {title}\n- **Year:** {pub_year} | **Citations:** {cites} | **Venue:** {venue}\n- **Authors:** {', '.join(authors[:4])}\n- **Link:** {landing_url}\n")
        return "\n".join(out)
    except Exception as e:
        return f"OpenAlex error: {e}"

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
            res = {"jsonrpc": "2.0", "id": mid, "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "openalex-mcp", "version": "1.0.0"}}}
        elif m == "tools/list":
            tools = [{
                "name": "openalex_search",
                "description": "Search global academic literature (250M+ scientific papers, citations, books, across all disciplines) on OpenAlex.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Academic topic, author, paper title, or concept"},
                        "per_page": {"type": "integer", "default": 5}
                    },
                    "required": ["query"]
                }
            }]
            res = {"jsonrpc": "2.0", "id": mid, "result": {"tools": tools}}
        elif m == "tools/call":
            params = req.get("params", {})
            args = params.get("arguments", {})
            text = search_openalex(args.get("query", ""), int(args.get("per_page", 5)))
            res = {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": text}]}}
        else:
            res = {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "Method not found"}}
        sys.stdout.write(json.dumps(res) + "\n")
        sys.stdout.flush()

if __name__ == "__main__":
    main()
