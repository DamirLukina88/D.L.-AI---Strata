#!/usr/bin/env python3
"""osm_mcp.py - Free OpenStreetMap Nominatim geolocation MCP server."""
import sys
import json
import urllib.request
import urllib.parse

def geocode_osm(query: str) -> str:
    try:
        encoded = urllib.parse.quote(query)
        url = f"https://nominatim.openstreetmap.org/search?q={encoded}&format=json&limit=3&addressdetails=1"
        req = urllib.request.Request(url, headers={"User-Agent": "DL-AI-Strata/1.0 (info@damir-lukina.com)"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode("utf-8"))
        
        if not data:
            return f"No geographic locations found on OpenStreetMap for: {query}"
        
        lines = []
        for loc in data:
            name = loc.get("display_name", "")
            lat = loc.get("lat")
            lon = loc.get("lon")
            cat = loc.get("type", "location")
            lines.append(f"### {name}\n- **Coordinates:** {lat}, {lon}\n- **Type:** {cat}\n- **Map Link:** https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map=16/{lat}/{lon}\n")
        return "\n".join(lines)
    except Exception as e:
        return f"OpenStreetMap error: {e}"

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
            res = {"jsonrpc": "2.0", "id": mid, "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "osm-mcp", "version": "1.0.0"}}}
        elif m == "tools/list":
            tools = [{
                "name": "osm_geocode",
                "description": "Geocode addresses, cities, landmarks, and geographic coordinates worldwide via OpenStreetMap.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Address, city name, landmark, or location query"}
                    },
                    "required": ["query"]
                }
            }]
            res = {"jsonrpc": "2.0", "id": mid, "result": {"tools": tools}}
        elif m == "tools/call":
            params = req.get("params", {})
            args = params.get("arguments", {})
            text = geocode_osm(args.get("query", ""))
            res = {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": text}]}}
        else:
            res = {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "Method not found"}}
        sys.stdout.write(json.dumps(res) + "\n")
        sys.stdout.flush()

if __name__ == "__main__":
    main()
