#!/usr/bin/env python3
"""clinicaltrials_mcp.py - Free ClinicalTrials.gov API v2 MCP server."""
import sys
import json
import urllib.request
import urllib.parse

def search_trials(condition: str = "", drug: str = "", max_results: int = 5) -> str:
    try:
        params = [f"pageSize={max_results}"]
        if condition:
            params.append(f"query.cond={urllib.parse.quote(condition)}")
        if drug:
            params.append(f"query.intr={urllib.parse.quote(drug)}")
        query_str = "&".join(params)
        url = f"https://clinicaltrials.gov/api/v2/studies?{query_str}"
        
        req = urllib.request.Request(url, headers={"User-Agent": "DL-AI-Strata/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8"))
        
        studies = data.get("studies", [])
        if not studies:
            return f"No clinical trials found matching condition: '{condition}', intervention: '{drug}'."
        
        lines = []
        for s in studies:
            proto = s.get("protocolSection", {})
            ident = proto.get("identificationModule", {})
            status = proto.get("statusModule", {})
            design = proto.get("designModule", {})
            
            nct = ident.get("nctId", "N/A")
            title = ident.get("briefTitle", "Untitled")
            overall_status = status.get("overallStatus", "Unknown")
            phases = ", ".join(design.get("phases", ["Not specified"]))
            sponsor = proto.get("sponsorCollaboratorsModule", {}).get("leadSponsor", {}).get("name", "Unknown")
            study_url = f"https://clinicaltrials.gov/study/{nct}"
            
            lines.append(f"### [{nct}] {title}\n- **Status:** {overall_status} | **Phase:** {phases}\n- **Sponsor:** {sponsor}\n- **Link:** {study_url}\n")
        return "\n".join(lines)
    except Exception as e:
        return f"ClinicalTrials.gov error: {e}"

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
            res = {"jsonrpc": "2.0", "id": mid, "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "clinicaltrials-mcp", "version": "1.0.0"}}}
        elif m == "tools/list":
            tools = [{
                "name": "clinicaltrials_search",
                "description": "Search ClinicalTrials.gov API v2 for medical studies, clinical trial phases, conditions, and experimental drugs.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "condition": {"type": "string", "description": "Disease or medical condition, e.g. Alzheimer, Diabetes, Melanoma"},
                        "drug": {"type": "string", "description": "Drug or intervention name, e.g. Pembrolizumab, Metformin"},
                        "max_results": {"type": "integer", "default": 5}
                    }
                }
            }]
            res = {"jsonrpc": "2.0", "id": mid, "result": {"tools": tools}}
        elif m == "tools/call":
            params = req.get("params", {})
            args = params.get("arguments", {})
            text = search_trials(args.get("condition", ""), args.get("drug", ""), int(args.get("max_results", 5)))
            res = {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": text}]}}
        else:
            res = {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "Method not found"}}
        _reply(req, res)

if __name__ == "__main__":
    main()
