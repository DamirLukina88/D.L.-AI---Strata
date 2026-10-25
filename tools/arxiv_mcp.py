#!/usr/bin/env python3
"""arxiv_mcp.py - Free arXiv preprints & research papers MCP server."""
import sys
import json
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET

def search_arxiv(query: str, max_results: int = 5) -> str:
    try:
        encoded = urllib.parse.quote(query)
        url = f"https://export.arxiv.org/api/query?search_query=all:{encoded}&start=0&max_results={max_results}"
        req = urllib.request.Request(url, headers={"User-Agent": "DL-AI-Strata/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            xml_data = r.read().decode("utf-8")
        
        root = ET.fromstring(xml_data)
        ns = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
        entries = root.findall("atom:entry", ns)
        if not entries:
            return f"No arXiv papers found matching query: {query}"
        
        results = []
        for e in entries:
            title = (e.find("atom:title", ns).text or "").strip().replace("\n", " ")
            summary = (e.find("atom:summary", ns).text or "").strip().replace("\n", " ")
            published = (e.find("atom:published", ns).text or "")[:10]
            authors = [a.find("atom:name", ns).text for a in e.findall("atom:author", ns)]
            link = e.find("atom:id", ns).text or ""
            pdf_link = link.replace("/abs/", "/pdf/") + ".pdf"
            results.append(f"### {title}\n- **Published:** {published}\n- **Authors:** {', '.join(authors[:5])}\n- **Links:** [arXiv Abstract]({link}) | [PDF]({pdf_link})\n- **Summary:** {summary[:500]}...\n")
        return "\n".join(results)
    except Exception as e:
        return f"arXiv API error: {e}"

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
            res = {"jsonrpc": "2.0", "id": mid, "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "arxiv-mcp", "version": "1.0.0"}}}
        elif m == "tools/list":
            tools = [{
                "name": "arxiv_search",
                "description": "Search arXiv for scientific papers, AI/ML models, physics, and computer science preprints.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query or topic"},
                        "max_results": {"type": "integer", "default": 5}
                    },
                    "required": ["query"]
                }
            }]
            res = {"jsonrpc": "2.0", "id": mid, "result": {"tools": tools}}
        elif m == "tools/call":
            params = req.get("params", {})
            args = params.get("arguments", {})
            text = search_arxiv(args.get("query", ""), int(args.get("max_results", 5)))
            res = {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": text}]}}
        else:
            res = {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "Method not found"}}
        sys.stdout.write(json.dumps(res) + "\n")
        sys.stdout.flush()

if __name__ == "__main__":
    main()
