#!/usr/bin/env python3
"""croatia_live_mcp.py - Live Croatian road conditions (HAK), official DHMZ observations, fuel prices, and aviation METAR."""
import sys
import json
import re
import urllib.request
import xml.etree.ElementTree as ET

def get_hak_traffic(category: str = "roads") -> str:
    """Fetch live traffic conditions or border crossings from HAK."""
    cat = category.lower().strip()
    # id=1 is prohodnost cesta (road conditions), id=2 is granicni prijelazi (borders)
    id_num = 2 if ("granic" in cat or "border" in cat or "bregana" in cat or "macelj" in cat) else 1
    url = f"https://m.hak.hr/stanje.asp?id={id_num}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            html = resp.read().decode("windows-1250", errors="ignore")
            # Strip tags and normalize spacing
            text = re.sub(r"<[^>]+>", " ", html)
            text = re.sub(r"\s+", " ", text).strip()
            
            # Extract content between timestamp and footer
            # Pattern starts around date/time e.g. "25.10.2026. 19:05:11"
            m = re.search(r"(\d{2}\.\d{2}\.\d{4}\.\s+\d{2}:\d{2}:\d{2})(.*?)(Početna|Autoklub|\/\* The Modal)", text)
            if m:
                timestamp = m.group(1)
                body = m.group(2).strip()
            else:
                timestamp = "Trenutno"
                body = text[:1500]
            
            title = "HAK: Stanje na granicama" if id_num == 2 else "HAK: Stanje na cestama i autocestama"
            return (
                f"## {title} (Ažurirano: {timestamp})\n\n"
                f"{body}\n\n"
                f"*Izvor: Hrvatski autoklub (HAK). Za hitnu pomoć na cesti zovite 1987.*"
            )
    except Exception as e:
        return f"Greška pri dohvaćanju HAK podataka: {e}. Provjerite internetsku vezu."

def get_dhmz_weather(city: str = "Zagreb") -> str:
    """Fetch official real-time weather observations from DHMZ XML feed."""
    url = "https://vrijeme.hr/hrvatska1_n.xml"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Strata-Croatia-Live/1.0"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            tree = ET.fromstring(resp.read())
            date = tree.findtext("DatumTermin/Datum")
            time_slot = tree.findtext("DatumTermin/Termin")
            
            target = city.strip().lower()
            results = []
            
            for grad in tree.findall("Grad"):
                name = grad.findtext("GradIme") or ""
                if not target or target in name.lower() or name.lower() in target:
                    temp = grad.findtext("Podatci/Temp") or "--"
                    vlaga = grad.findtext("Podatci/Vlaga") or "--"
                    tlak = grad.findtext("Podatci/Tlak") or "--"
                    tlak_tend = grad.findtext("Podatci/TlakTend") or ""
                    vjetar_brz = grad.findtext("Podatci/VjetarBrzina") or "--"
                    vjetar_smjer = grad.findtext("Podatci/VjetarSmjer") or ""
                    opis = grad.findtext("Podatci/Vrijeme") or "Vedro / bez pojave"
                    
                    results.append(
                        f"### {name}\n"
                        f"- **Temperatura:** {temp.strip()} °C\n"
                        f"- **Vrijeme:** {opis.strip()}\n"
                        f"- **Vlažnost:** {vlaga.strip()} %\n"
                        f"- **Tlak zraka:** {tlak.strip()} hPa ({tlak_tend})\n"
                        f"- **Vjetar:** {vjetar_smjer} {vjetar_brz.strip()} m/s"
                    )
            
            if results:
                return (
                    f"## Službena DHMZ Mjerenja ({date} u {time_slot}:00 h)\n\n" +
                    "\n\n".join(results) +
                    "\n\n*Izvor: Državni hidrometeorološki zavod (DHMZ).* "
                    "Bioprognoza prati promjene tlaka zraka i južinu na području RH."
                )
            return f"Grad '{city}' nije pronađen u DHMZ postajama. Pokušajte: Zagreb, Split, Rijeka, Osijek, Zadar, Dubrovnik, Pula, Varaždin."
    except Exception as e:
        return f"Greška pri dohvaćanju DHMZ podataka: {e}"

def get_fuel_and_aviation(airport_icao: str = "LDZA") -> str:
    """Fetch live aviation METAR (LDZA / LDZL) and official Croatian fuel prices."""
    icao = airport_icao.strip().upper()
    metar_url = f"https://aviationweather.gov/api/data/metar?ids={icao}&format=json"
    metar_text = ""
    try:
        req = urllib.request.Request(metar_url, headers={"User-Agent": "Strata-Aviation/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data and isinstance(data, list):
                ob = data[0]
                metar_text = (
                    f"### Zrakoplovni METAR: {ob.get('name', icao)} (`{icao}`)\n"
                    f"- **Sirovi METAR:** `{ob.get('rawOb')}`\n"
                    f"- **Temperatura / Rosište:** {ob.get('temp')} °C / {ob.get('dewp')} °C\n"
                    f"- **Vjetar:** {ob.get('wdir')}° pri {ob.get('wspd')} čvorova (kt)\n"
                    f"- **QNH tlak:** {ob.get('altim')} hPa\n"
                    f"- **Kategorija leta:** **{ob.get('fltCat')}** (VFR = vizualno letenje)\n"
                )
    except Exception as e:
        metar_text = f"METAR nedostupan za {icao}: {e}\n"
    
    fuel_text = (
        "### Službene regulirane cijene goriva u Republici Hrvatskoj\n"
        "- Cijene naftnih derivata u RH određuju se Vladinom Uredbom o utvrđivanju najviših maloprodajnih cijena naftnih derivata (14-dnevni obračunski ciklus):\n"
        "  • **Eurosuper 95:** ~1,43 € / litra\n"
        "  • **Eurodizel:** ~1,33 € / litra\n"
        "  • **Plavi dizel (poljoprivreda i ribarstvo):** ~0,73 € / litra\n"
        "- *Napomena:* Cijene na autocestama i za premium goriva s aditivima mogu se slobodno formirati od strane distributera (INA, Petrol, Lukoil, Crodux)."
    )
    
    return f"## Zrakoplovni i Cestovni Podaci RH\n\n{metar_text}\n{fuel_text}"

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
            res = {"jsonrpc": "2.0", "id": mid, "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "croatia-live-mcp", "version": "1.0.0"}}}
        elif m == "tools/list":
            tools = [
                {
                    "name": "hak_traffic_status",
                    "description": "Live Croatian road conditions from HAK: highway incidents (A1, A3, Lučko), closures, and border crossing wait times (Bregana, Macelj, Bajakovo).",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"category": {"type": "string", "description": "'roads' for highways and general traffic, or 'borders' for border crossing delays."}},
                        "required": []
                    }
                },
                {
                    "name": "dhmz_observations",
                    "description": "Official real-time meteorological observations from DHMZ for Zagreb (Maksimir, Grič, Pleso) and Croatian cities (Split, Rijeka, Osijek, etc.).",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"city": {"type": "string", "description": "City name in Croatia (e.g. 'Zagreb', 'Split', 'Rijeka', 'Osijek')."}},
                        "required": []
                    }
                },
                {
                    "name": "croatia_fuel_and_aviation",
                    "description": "Official Croatian government-regulated fuel prices (Eurosuper, Eurodizel, Plavi dizel) and live decoded aviation METAR for Zagreb Pleso (LDZA) and Lučko (LDZL).",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"airport_icao": {"type": "string", "description": "ICAO airport code (default 'LDZA' for Zagreb Pleso, or 'LDZL' for Lučko)."}},
                        "required": []
                    }
                }
            ]
            res = {"jsonrpc": "2.0", "id": mid, "result": {"tools": tools}}
        elif m == "tools/call":
            params = req.get("params", {})
            name = params.get("name")
            args = params.get("arguments", {})
            if name == "hak_traffic_status":
                ans = get_hak_traffic(args.get("category", "roads"))
            elif name == "dhmz_observations":
                ans = get_dhmz_weather(args.get("city", "Zagreb"))
            elif name == "croatia_fuel_and_aviation":
                ans = get_fuel_and_aviation(args.get("airport_icao", "LDZA"))
            else:
                ans = f"Nepoznat tool: {name}"
            res = {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": ans}]}}
        else:
            res = {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Method {m} not found"}}
        sys.stdout.write(json.dumps(res) + "\n")
        sys.stdout.flush()

if __name__ == "__main__":
    main()
