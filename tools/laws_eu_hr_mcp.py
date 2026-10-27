#!/usr/bin/env python3
"""laws_eu_hr_mcp.py - Free Croatian (Zakon.hr / Narodne Novine) & EU (EUR-Lex / CURIA) Laws MCP server."""
import sys
import json
import urllib.request
import urllib.parse
import re

HR_LAWS = {
    "zakon o radu": "https://www.zakon.hr/z/307/Zakon-o-radu",
    "zakon o obveznim odnosima": "https://www.zakon.hr/z/75/Zakon-o-obveznim-odnosima",
    "ovrsni zakon": "https://www.zakon.hr/z/256/Ovr%C5%A1ni-zakon",
    "zakon o trgovackim drustvima": "https://www.zakon.hr/z/212/Zakon-o-trgova%C4%8Dkim-dru%C5%A1tvima",
    "zakon o porezu na dodanu vrijednost": "https://www.zakon.hr/z/590/Zakon-o-porezu-na-dodanu-vrijednost-PDV",
    "opci porezni zakon": "https://www.zakon.hr/z/100/Op%C4%87i-porezni-zakon",
    "zakon o zastiti osobnih podataka": "https://www.zakon.hr/z/383/Zakon-o-provedbi-Op%C4%87e-uredbe-o-za%C5%A1titi-podataka"
}

def lookup_hr_law(query: str) -> str:
    q = query.lower().strip()
    for k, v in HR_LAWS.items():
        if k in q or q in k:
            return f"## Hrvatsko zakonodavstvo: {k.title()}\n- **Službeni pročišćeni tekst:** {v}\n- **Izvor:** Narodne Novine / Središnji državni portal RH (zakon.hr)"
    return f"Upit '{query}' za hrvatske zakone. Pretražite službeni registar zakona na https://narodne-novine.nn.hr ili https://www.zakon.hr"

def lookup_eu_law(query: str) -> str:
    try:
        # Query EUR-Lex portal search
        encoded = urllib.parse.quote(query)
        search_url = f"https://eur-lex.europa.eu/search.html?scope=EURLEX&text={encoded}&lang=hr&type=quick"
        
        # Recognized EU landmark acts
        landmarks = {
            "ai act": ("Uredba o umjetnoj inteligenciji (EU AI Act - Regulation 2024/1689)", "https://eur-lex.europa.eu/legal-content/HR/TXT/?uri=CELEX:32024R1689"),
            "gdpr": ("Opća uredba o zaštiti podataka (GDPR - Regulation 2016/679)", "https://eur-lex.europa.eu/legal-content/HR/TXT/?uri=CELEX:32016R0679"),
            "cra": ("Akt o kiberotpornosti (Cyber Resilience Act - CRA)", "https://eur-lex.europa.eu/legal-content/HR/TXT/?uri=CELEX:52022PC0454"),
            "dma": ("Akt o digitalnim tržištima (Digital Markets Act - DMA)", "https://eur-lex.europa.eu/legal-content/HR/TXT/?uri=CELEX:32022R1925"),
            "dsa": ("Akt o digitalnim uslugama (Digital Services Act - DSA)", "https://eur-lex.europa.eu/legal-content/HR/TXT/?uri=CELEX:32022R2065")
        }
        for k, (name, link) in landmarks.items():
            if k in query.lower():
                return f"## Pravo Europske unije (EUR-Lex): {name}\n- **Službeni puni tekst na hrvatskom jeziku:** {link}\n- **Službeni portal Suda EU (CURIA):** https://curia.europa.eu/juris/recherche.jsf"
        
        return f"## Pretraga prava Europske unije (EUR-Lex): '{query}'\n- **Izravna poveznica na pročišćene akte EU:** {search_url}\n- **Baza presuda Suda Europske unije (CURIA):** https://curia.europa.eu"
    except Exception as e:
        return f"EUR-Lex lookup error: {e}"

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
            res = {"jsonrpc": "2.0", "id": mid, "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "laws-eu-hr-mcp", "version": "1.0.0"}}}
        elif m == "tools/list":
            tools = [
                {
                    "name": "hr_law_lookup",
                    "description": "Pretraži službene zakone i propise Republike Hrvatske (Zakon o radu, ZOO, Ovršni zakon, PDV) iz Narodnih Novina i Zakon.hr.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Naziv zakona ili pravnog instituta, npr. 'Zakon o radu', 'otkazni rok', 'ovrha'"}
                        },
                        "required": ["query"]
                    }
                },
                {
                    "name": "eu_law_lookup",
                    "description": "Pretraži zakonodavstvo Europske unije (EUR-Lex: EU AI Act, GDPR, CRA, DMA) i sudsku praksu Suda EU (CURIA).",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Propis ili uredba EU, npr. 'AI Act', 'GDPR', 'Cyber Resilience Act', 'autorsko pravo'"}
                        },
                        "required": ["query"]
                    }
                }
            ]
            res = {"jsonrpc": "2.0", "id": mid, "result": {"tools": tools}}
        elif m == "tools/call":
            params = req.get("params", {})
            name = params.get("name")
            args = params.get("arguments", {})
            if name == "hr_law_lookup":
                text = lookup_hr_law(args.get("query", ""))
            elif name == "eu_law_lookup":
                text = lookup_eu_law(args.get("query", ""))
            else:
                text = f"Unknown tool: {name}"
            res = {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": text}]}}
        else:
            res = {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "Method not found"}}
        _reply(req, res)

if __name__ == "__main__":
    main()
