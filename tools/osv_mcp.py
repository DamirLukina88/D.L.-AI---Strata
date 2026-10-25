#!/usr/bin/env python3
"""osv_mcp.py - Free Open Source Vulnerabilities (OSV.dev) database MCP server."""
import sys
import json
import urllib.request

def check_vulns(package_name: str, ecosystem: str = "PyPI", version: str = "") -> str:
    try:
        url = "https://api.osv.dev/v1/query"
        payload = {"package": {"name": package_name, "ecosystem": ecosystem}}
        if version:
            payload["version"] = version
        
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "DL-AI-Strata/1.0"}
        )
        with urllib.request.urlopen(req, timeout=12) as r:
            data = json.loads(r.read().decode("utf-8"))
        
        vulns = data.get("vulns", [])
        if not vulns:
            v_str = f" v{version}" if version else ""
            return f"No known open vulnerabilities found for {package_name}{v_str} in {ecosystem}."
        
        lines = [f"Found {len(vulns)} vulnerability report(s) for {package_name} ({ecosystem}):\n"]
        for v in vulns[:5]:
            vid = v.get("id", "Unknown")
            summary = v.get("summary", "No summary available")
            details = (v.get("details") or "")[:200]
            aliases = ", ".join(v.get("aliases", []))
            lines.append(f"### {vid} ({aliases or 'No alias'})\n- **Summary:** {summary}\n- **Details:** {details}...\n")
        if len(vulns) > 5:
            lines.append(f"*...and {len(vulns) - 5} more advisories.*")
        return "\n".join(lines)
    except Exception as e:
        return f"OSV query error: {e}"

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
            res = {"jsonrpc": "2.0", "id": mid, "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "osv-mcp", "version": "1.0.0"}}}
        elif m == "tools/list":
            tools = [{
                "name": "osv_security_scan",
                "description": "Scan software packages and libraries for known security vulnerabilities (CVEs) via OSV.dev.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "package": {"type": "string", "description": "Package name, e.g. jinja2, express, requests"},
                        "ecosystem": {"type": "string", "enum": ["PyPI", "npm", "Go", "crates.io", "Maven", "NuGet"], "default": "PyPI"},
                        "version": {"type": "string", "description": "Optional exact package version to check"}
                    },
                    "required": ["package"]
                }
            }]
            res = {"jsonrpc": "2.0", "id": mid, "result": {"tools": tools}}
        elif m == "tools/call":
            params = req.get("params", {})
            args = params.get("arguments", {})
            text = check_vulns(args.get("package", ""), args.get("ecosystem", "PyPI"), args.get("version", ""))
            res = {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": text}]}}
        else:
            res = {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "Method not found"}}
        sys.stdout.write(json.dumps(res) + "\n")
        sys.stdout.flush()

if __name__ == "__main__":
    main()
