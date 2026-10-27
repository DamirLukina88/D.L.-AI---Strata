#!/usr/bin/env python3
"""pubchem_mcp.py - Free PubChem NCBI chemical and compound database MCP server."""
import sys
import json
import urllib.request
import urllib.parse

def lookup_compound(name: str) -> str:
    try:
        encoded = urllib.parse.quote(name)
        url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{encoded}/property/MolecularFormula,MolecularWeight,CanonicalSMILES,IUPACName,InChIKey/JSON"
        req = urllib.request.Request(url, headers={"User-Agent": "DL-AI-Strata/1.0"})
        with urllib.request.urlopen(req, timeout=12) as r:
            data = json.loads(r.read().decode("utf-8"))
        
        props = data.get("PropertyTable", {}).get("Properties", [])
        if not props:
            return f"No compound properties found for {name}."
        p = props[0]
        cid = p.get("CID")
        formula = p.get("MolecularFormula", "N/A")
        mw = p.get("MolecularWeight", "N/A")
        smiles = p.get("CanonicalSMILES", "N/A")
        iupac = p.get("IUPACName", "N/A")
        inchikey = p.get("InChIKey", "N/A")
        pubchem_url = f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}"
        
        return f"## Compound: {name} (CID: {cid})\n- **IUPAC Name:** {iupac}\n- **Molecular Formula:** {formula}\n- **Molecular Weight:** {mw} g/mol\n- **SMILES:** `{smiles}`\n- **InChIKey:** `{inchikey}`\n- **PubChem Link:** {pubchem_url}"
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return f"Compound '{name}' not found in PubChem."
        return f"PubChem HTTP Error: {e}"
    except Exception as e:
        return f"PubChem query error: {e}"

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
            res = {"jsonrpc": "2.0", "id": mid, "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "pubchem-mcp", "version": "1.0.0"}}}
        elif m == "tools/list":
            tools = [{
                "name": "pubchem_lookup",
                "description": "Look up chemical structures, molecular formulas, molecular weights, and SMILES via PubChem.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Chemical name, drug name, or compound (e.g. caffeine, aspirin, ibuprofen)"}
                    },
                    "required": ["name"]
                }
            }]
            res = {"jsonrpc": "2.0", "id": mid, "result": {"tools": tools}}
        elif m == "tools/call":
            params = req.get("params", {})
            args = params.get("arguments", {})
            text = lookup_compound(args.get("name", ""))
            res = {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": text}]}}
        else:
            res = {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "Method not found"}}
        _reply(req, res)

if __name__ == "__main__":
    main()
