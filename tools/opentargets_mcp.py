#!/usr/bin/env python3
"""opentargets_mcp.py - Free Open Targets Platform GraphQL MCP server."""
import sys
import json
import urllib.request

def query_target(gene_symbol: str) -> str:
    try:
        # Search for target ID first
        search_query = """
        query Search($queryString: String!) {
          search(queryString: $queryString, entityNames: ["target"], page: {size: 1, index: 0}) {
            hits {
              id
              name
              description
              entity
            }
          }
        }
        """
        req_search = urllib.request.Request(
            "https://api.platform.opentargets.org/api/v4/graphql",
            data=json.dumps({"query": search_query, "variables": {"queryString": gene_symbol}}).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "DL-AI-Strata/1.0"}
        )
        with urllib.request.urlopen(req_search, timeout=12) as r:
            sdata = json.loads(r.read().decode("utf-8"))
        
        hits = sdata.get("data", {}).get("search", {}).get("hits", [])
        if not hits:
            return f"No target found in Open Targets for gene/protein symbol: {gene_symbol}."
        
        target_id = hits[0]["id"]
        target_name = hits[0]["name"]
        
        # Query details and associated diseases
        detail_query = """
        query TargetDetails($ensemblId: String!) {
          target(ensemblId: $ensemblId) {
            id
            approvedSymbol
            approvedName
            functionDescriptions
            associatedDiseases(page: {size: 5, index: 0}) {
              count
              rows {
                disease {
                  id
                  name
                }
                score
              }
            }
          }
        }
        """
        req_detail = urllib.request.Request(
            "https://api.platform.opentargets.org/api/v4/graphql",
            data=json.dumps({"query": detail_query, "variables": {"ensemblId": target_id}}).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "DL-AI-Strata/1.0"}
        )
        with urllib.request.urlopen(req_detail, timeout=12) as r:
            tdata = json.loads(r.read().decode("utf-8"))
        
        t = tdata.get("data", {}).get("target", {})
        symbol = t.get("approvedSymbol", gene_symbol)
        name = t.get("approvedName", target_name)
        funcs = t.get("functionDescriptions", [])
        func_summary = funcs[0] if funcs else "No function description available."
        
        diseases = t.get("associatedDiseases", {}).get("rows", [])
        total_diseases = t.get("associatedDiseases", {}).get("count", 0)
        
        lines = [
            f"## Target: {symbol} - {name} (Ensembl: {target_id})",
            f"- **Function:** {func_summary[:300]}...",
            f"- **Top Associated Diseases (out of {total_diseases}):**"
        ]
        for d in diseases:
            d_name = d.get("disease", {}).get("name", "Unknown")
            score = round(d.get("score", 0), 3)
            lines.append(f"  • {d_name} (Association Score: {score})")
        lines.append(f"- **OpenTargets Profile:** https://platform.opentargets.org/target/{target_id}")
        return "\n".join(lines)
    except Exception as e:
        return f"Open Targets API error: {e}"

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
            res = {"jsonrpc": "2.0", "id": mid, "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "opentargets-mcp", "version": "1.0.0"}}}
        elif m == "tools/list":
            tools = [{
                "name": "opentargets_lookup",
                "description": "Look up therapeutic drug targets, gene functions, and disease associations in Open Targets Platform.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "gene_symbol": {"type": "string", "description": "Gene or target symbol, e.g. TP53, EGFR, BRCA1, ACE2"}
                    },
                    "required": ["gene_symbol"]
                }
            }]
            res = {"jsonrpc": "2.0", "id": mid, "result": {"tools": tools}}
        elif m == "tools/call":
            params = req.get("params", {})
            args = params.get("arguments", {})
            text = query_target(args.get("gene_symbol", ""))
            res = {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": text}]}}
        else:
            res = {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "Method not found"}}
        _reply(req, res)

if __name__ == "__main__":
    main()
