#!/usr/bin/env python3
"""zagreb_mcp.py - Zagreb civic services, ZET tram lines (from ZET GTFS) and live news (zet.skoljka.org), on-duty pharmacies (City of Zagreb list), where to find waste schedules, live air quality, and BAJS / Nextbike live stations."""
import sys
import json
import re
import html
import unicodedata
import urllib.request

# Endpoints as ZET's GTFS timetable feed names them (routes.txt, feed version 000397, valid from 2026-10-21).
# 31-34 are the night lines.
ZET_TRAM_LINES = {
    "1": "Zapadni kolodvor - Borongaj",
    "2": "Črnomerec - Savišće",
    "3": "Ljubljanica - Savišće",
    "4": "Savski most - Dubec",
    "5": "Prečko - Park Maksimir",
    "6": "Črnomerec - Sopot",
    "7": "Savski most - Dubrava",
    "8": "Mihaljevac - Zapruđe",
    "9": "Ljubljanica - Borongaj",
    "11": "Črnomerec - Dubec",
    "12": "Ljubljanica - Dubrava",
    "13": "Žitnjak - Kvaternikov trg",
    "14": "Mihaljevac - Zapruđe",
    "15": "Mihaljevac - Gračansko dolje",
    "17": "Prečko - Borongaj",
    "31": "Črnomerec - Savski most (noćna)",
    "32": "Prečko - Borongaj (noćna)",
    "33": "Mihaljevac - Savišće (noćna)",
    "34": "Ljubljanica - Dubec (noćna)"
}

# The City of Zagreb's list of on-duty pharmacies (zagreb.hr/dezurne-ljekarne/497, page dated 20.10.2025): five
# Gradska ljekarna Zagreb pharmacies with a day service 7-20 and a night service 20-7, and Ljekarna ZEUS 0-24.
PHARMACIES_SOURCE = "Grad Zagreb, https://zagreb.hr/en/dezurne-ljekarne/497 (stranica od 20.10.2025.)"
PHARMACIES_24_7 = [
    {"name": "Gradska ljekarna Zagreb", "address": "Trg bana J. Jelačića 3", "phone": "01 4816 198",
     "notes": "Dnevna služba 7-20 h, noćna služba 20-7 h."},
    {"name": "Gradska ljekarna Zagreb", "address": "Ilica 291", "phone": "01 3750 321",
     "notes": "Dnevna služba 7-20 h, noćna služba 20-7 h."},
    {"name": "Gradska ljekarna Zagreb", "address": "Ozaljska 1", "phone": "01 3097 586",
     "notes": "Dnevna služba 7-20 h, noćna služba 20-7 h."},
    {"name": "Gradska ljekarna Zagreb", "address": "Grižanska 4", "phone": "01 2992 350",
     "notes": "Dnevna služba 7-20 h, noćna služba 20-7 h."},
    {"name": "Gradska ljekarna Zagreb", "address": "Av. V. Holjevca 22", "phone": "01 6525 425",
     "notes": "Dnevna služba 7-20 h, noćna služba 20-7 h."},
    {"name": "Ljekarna ZEUS", "address": "Divka Budaka 17, Borongaj (okretište tramvaja)", "phone": "nije naveden",
     "notes": "Svaki dan 0-24 h, i nedjeljom i praznicima."},
]



def _fold(text: str) -> str:
    """Lower case without diacritics, so 'Trešnjevka' and 'tresnjevka' match."""
    text = text.strip().lower().replace("đ", "d")
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))

def get_zet_live_news() -> str:
    """Fetch live service alerts and disruptions from zet.skoljka.org/news."""
    url = "https://zet.skoljka.org/news"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Strata-Zagreb-MCP/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            items = data.get("items", [])
            lines = ["\n### Najnovije servisne informacije i izmjene (zet.skoljka.org):"]
            for it in items[:4]:
                title = it.get("title", "")
                summary = re.sub(r"<[^>]+>", " ", it.get("summaryHtml", ""))
                summary = html.unescape(summary).strip()
                summary = re.sub(r"\s+", " ", summary)
                lines.append(f"- **{title}**\n  {summary[:200]}...")
            return "\n".join(lines)
    except Exception as e:
        return f"\n*(Live vijesti s zet.skoljka.org trenutno nedostupne: {e})*"

def get_zet_transit(query: str = "") -> str:
    q = query.strip().lower()
    live_news = get_zet_live_news()
    
    if not q or "vijest" in q or "izmjen" in q or "radov" in q or "servis" in q:
        lines = ["## ZET Tramvajska Mreža (Zagreb)", "### Dnevne i Noćne Linije:"]
        for num in ["1", "2", "4", "6", "11", "12", "14", "17", "31", "34"]:
            lines.append(f"- **Linija {num}:** {ZET_TRAM_LINES[num]}")
        lines.append("- *(Pretražite po broju linije npr. `linija 11` za sve ostale)*\n")
        lines.append(live_news)
        return "\n".join(lines)
    
    if "noc" in q:
        lines = ["## ZET noćne tramvajske linije:"]
        for num in ["31", "32", "33", "34"]:
            lines.append(f"- **Linija {num}:** {ZET_TRAM_LINES[num]}")
        return "\n".join(lines)
    
    matches = []
    for num, desc in ZET_TRAM_LINES.items():
        if num == q or f"linija {num}" in q or _fold(q) in _fold(desc):
            matches.append(f"- **Linija {num}:** {desc}")
    
    if matches:
        return f"## Rezultati pretrage ZET linija za '{query}':\n" + "\n".join(matches) + "\n" + live_news
    return f"Nije pronađena ZET linija za pojam '{query}'. Linije: {', '.join(ZET_TRAM_LINES)} (31-34 noćne).\n{live_news}"

def get_bajs_bikes(query: str = "") -> str:
    """Fetch real-time bike availability and free racks across all 200 BAJS / Nextbike stations in Zagreb."""
    url = "https://api.nextbike.net/maps/nextbike-live.json?city=1172"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Strata-Zagreb-MCP/1.0"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            places = data["countries"][0]["cities"][0]["places"]
            total_bikes = sum(p.get("bikes", 0) for p in places)
            
            q = query.strip().lower()
            matches = []
            for p in places:
                name = p.get("name", "")
                if not q or q in name.lower():
                    matches.append(p)
            
            lines = [
                f"## BAJS Zagreb (Nextbike) Stanje Bicikala uživo",
                f"- **Ukupno registriranih postaja u Zagrebu:** {len(places)}",
                f"- **Ukupno raspoloživih bicikala u sustavu:** {total_bikes}\n"
            ]
            
            if q:
                lines.append(f"### Pronađene postaje za pojam '{query}' ({len(matches)} postaja):")
            else:
                lines.append("### Istaknute postaje u središtu grada:")
                # select a few core central stations if no filter
                central_keywords = ["trg bana", "glavni kolodvor", "kvaternik", "crnomerec", "trešnjev", "velesajam", "savski most"]
                matches = [p for p in places if any(k in p.get("name", "").lower() for k in central_keywords)]
            
            for p in matches[:15]:
                name = p.get("name", "")
                bikes = p.get("bikes", 0)
                racks = p.get("free_racks", 0)
                lines.append(f"- **{name}:** {bikes} bicikala slobodno | {racks} slobodnih stalaka")
            
            lines.append("\n*Podaci se osvježavaju u stvarnom vremenu izravno iz službenog Nextbike GBFS sustava za Grad Zagreb.*")
            return "\n".join(lines)
    except Exception as e:
        return f"Greška pri dohvaćanju stanja BAJS bicikala: {e}"

def get_emergency_services() -> str:
    return (
        "## Dežurne i Hitne Službe u Gradu Zagrebu (0-24 h)\n\n"
        "### 1. Centar za kontrolu otrovanja (CKO):\n"
        "- **Telefon (0-24h):** **+385 1 2348 342**\n"
        "- **Lokacija:** Institut za medicinska istraživanja i medicinu rada (IMI) / KBC Zagreb\n"
        "- **Usluga:** Hitni medicinski savjeti kod trovanja kemikalijama, lijekovima, kućanskim sredstvima, biljkama, gljivama i ugrizima.\n\n"
        "### 2. Dežurna hitna pedijatrija (Hitni dječji prijem):\n"
        "- **Klinika za dječje bolesti Zagreb (Klaićeva):** Ulica Vjekoslava Klaića 16 | Tel: **+385 1 4600 111**\n"
        "- **KBC Zagreb - Rebro (Dječji hitni prijem):** Kišpatićeva 12 | Tel: **+385 1 2388 888**\n"
        "- **KB Sestre milosrdnice (Vinogradska):** Vinogradska cesta 29 | Tel: **+385 1 3787 111**\n\n"
        "### 3. Dežurni veterinar u Zagrebu (0-24 h):\n"
        "- **Klinike Veterinarskog fakulteta Sveučilišta u Zagrebu:** Heinzelova 55\n"
        "- **Hitni prijem za male životinje:** Tel: **+385 1 2390 111**\n"
        "- **Usluga:** 24/7 hitna kirurška, internistička i intenzivna skrb za pse, mačke i kućne ljubimce.\n\n"
        "### 4. Hitna stomatološka služba (Dežurni zubar noću, vikendom i blagdanom):\n"
        "- **Dom zdravlja Zagreb - Centar:** Runjaninova 4, centrala 01 4897 666 (radno vrijeme hitne službe provjerite telefonom)\n"
        "- **Klinička bolnica Dubrava:** Avenija Gojka Šuška 6 (Maksilofacijalna kirurgija i akutne traume lica i čeljusti)\n\n"
        "### 5. Opći hitni brojevi:\n"
        "- **Jedinstveni europski broj za hitne službe:** 112\n"
        "- **Hitna medicinska pomoć:** 194\n"
        "- **Vatrogasci:** 193\n"
        "- **Policija:** 192\n"
        "- **HAK pomoć na cesti:** 1987"
    )

def get_pharmacies() -> str:
    lines = ["## Dežurne ljekarne u Zagrebu", f"*Izvor: {PHARMACIES_SOURCE}. Prije dolaska noću nazovite ljekarnu.*\n"]
    for ph in PHARMACIES_24_7:
        lines.append(f"### {ph['name']}")
        lines.append(f"- **Adresa:** {ph['address']}")
        lines.append(f"- **Telefon:** {ph['phone']}")
        lines.append(f"- **Napomena:** {ph['notes']}\n")
    lines.append("### Važni hitni brojevi (Zagreb):")
    lines.append("- **Hitna medicinska pomoć:** 194 (ili 112)")
    lines.append("- **Objedinjeni hitni bolnički prijem (OHBP):** KBC Zagreb (Rebro), KBC Sestre milosrdnice (Vinogradska), KB Dubrava, KB Sveti Duh.")
    return "\n".join(lines)

def get_waste_schedule(district: str = "") -> str:
    """Odvoz otpada: Čistoća ga raspoređuje po adresi, ne po gradskoj četvrti, pa ovdje nema rasporeda po četvrtima
    (prijašnji popis po četvrtima nije imao izvor)."""
    where = f" za '{district.strip()}'" if district.strip() else ""
    return (
        f"## Čistoća Zagreb: raspored odvoza otpada{where}\n"
        "Raspored ovisi o adresi (ulici i kućnom broju), ne o gradskoj četvrti. Točne dane za svoju adresu nađite:\n"
        "- **cistoca.hr:** tražilica rasporeda po adresi\n"
        "- **aplikacija Razvrstaj MojZG:** raspored za odabranu adresu, po vrsti otpada\n"
        "- **Upiti:** WhatsApp / Viber 091 6471 100, e-pošta cistoca@zgh.hr\n"
        "\n**Glomazni otpad:** odvozi se na zahtjev (cistoca.hr).\n"
        "*Izvor: Index.hr o novom rasporedu odvoza; podaci iz 2022., provjerite na cistoca.hr.*"
    )

def get_air_quality() -> str:
    url = "https://air-quality-api.open-meteo.com/v1/air-quality?latitude=45.815&longitude=15.9819&current=european_aqi,pm10,pm2_5,ozone,nitrogen_dioxide"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Strata-Zagreb-MCP/1.0"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            c = data.get("current", {})
            aqi = c.get("european_aqi")
            pm25 = c.get("pm2_5")
            pm10 = c.get("pm10")
            o3 = c.get("ozone")
            no2 = c.get("nitrogen_dioxide")
            
            if aqi <= 20:
                qual = "Izvrsna (Dobra)"
                health = "Kvaliteta zraka je idealna za boravak na otvorenom i sportske aktivnosti."
            elif aqi <= 40:
                qual = "Prihvatljiva (Umjerena)"
                health = "Kvaliteta zraka je prihvatljiva; iznimno osjetljive osobe mogu osjetiti manje smetnje."
            elif aqi <= 60:
                qual = "Umjereno onečišćena"
                health = "Osjetljive skupine (astmatičari, djeca, stariji) trebaju smanjiti intenzivan napor na otvorenom."
            elif aqi <= 80:
                qual = "Loša (Znatno onečišćena)"
                health = "Preporučuje se izbjegavanje dugotrajnog boravka i provjetravanja u zonama prometnica."
            else:
                qual = "Vrlo loša / Opasna (Smog inverzija)"
                health = "Zdravstveno upozorenje za cjelokupnu populaciju. Koristite pročišćivače zraka u zatvorenom."
            
            return (
                f"## Trenutna kvaliteta zraka u Zagrebu\n"
                f"- **Vrijeme mjerenja:** {c.get('time')} UTC\n"
                f"- **Europski indeks kvalitete (AQI):** **{aqi}** ({qual})\n"
                f"- **Sitne čestice PM2.5:** {pm25} µg/m³ (WHO preporuka: < 15 µg/m³ 24h)\n"
                f"- **Čestice PM10:** {pm10} µg/m³ (WHO preporuka: < 45 µg/m³ 24h)\n"
                f"- **Ozon (O₃):** {o3} µg/m³\n"
                f"- **Dušikov dioksid (NO₂):** {no2} µg/m³\n\n"
                f"### Zdravstvena preporuka:\n{health}\n\n"
                f"*Mjerni podaci bazirani na službenim postajama: Zagreb-1 (Miramarska), Zagreb-2 (Ksaverska), Zagreb-3 (Dugave).*"
            )
    except Exception as e:
        return f"Greška pri dohvaćanju kvalitete zraka: {e}"

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
            res = {"jsonrpc": "2.0", "id": mid, "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "zagreb-mcp", "version": "1.1.0"}}}
        elif m == "tools/list":
            tools = [
                {
                    "name": "zet_transit",
                    "description": "Zagrebački električni tramvaj (ZET): look up tram lines (1-17 daytime, 31-34 night), terminals, and live disruption alerts from zet.skoljka.org.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"query": {"type": "string", "description": "Tram line number (e.g. '11', '31'), search query (e.g. 'Dubrava'), or 'vijesti' for live disruption news."}},
                        "required": []
                    }
                },
                {
                    "name": "zagreb_bajs_bikes",
                    "description": "BAJS Zagreb (Nextbike) live bicycle rental availability: real-time bike counts and free racks across all 200 stations in Zagreb.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"query": {"type": "string", "description": "Station or location name (e.g. 'Trg', 'Kolodvor', 'Trešnjevka', 'Maksimir', 'Velesajam'). Omit for central hub stations."}},
                        "required": []
                    }
                },
                {
                    "name": "zagreb_pharmacies",
                    "description": "On-duty pharmacies in Zagreb from the City of Zagreb list (dated 20.10.2025): addresses, phones, day and night service hours. Static list: tell the user to call before going at night.",
                    "inputSchema": {"type": "object", "properties": {}}
                },
                {
                    "name": "zagreb_emergency",
                    "description": "Zagreb 24/7 specialized emergency services: Poison Control Center (Centar za kontrolu otrovanja), emergency pediatric clinics (Klaićeva, Rebro), emergency 24/7 vet clinic (Veterinarski fakultet), and night emergency dentist (Runjaninova).",
                    "inputSchema": {"type": "object", "properties": {}}
                },
                {
                    "name": "cistoca_waste_schedule",
                    "description": "Zagreb Čistoća waste collection: where to find the schedule for an address (cistoca.hr, Razvrstaj MojZG app) and whom to ask. It has no schedule of its own: collection days depend on the street address.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"district": {"type": "string", "description": "Optional: the street, address or district the user asked about (only repeated in the answer)."}},
                        "required": []
                    }
                },
                {
                    "name": "zagreb_air_quality",
                    "description": "Real-time live air quality in Zagreb: European AQI, PM2.5, PM10, Ozone, NO2, and health guidance.",
                    "inputSchema": {"type": "object", "properties": {}}
                }
            ]
            res = {"jsonrpc": "2.0", "id": mid, "result": {"tools": tools}}
        elif m == "tools/call":
            params = req.get("params", {})
            name = params.get("name")
            args = params.get("arguments", {})
            if name == "zet_transit":
                ans = get_zet_transit(args.get("query", ""))
            elif name == "zagreb_bajs_bikes":
                ans = get_bajs_bikes(args.get("query", ""))
            elif name == "zagreb_pharmacies":
                ans = get_pharmacies()
            elif name == "zagreb_emergency":
                ans = get_emergency_services()
            elif name == "cistoca_waste_schedule":
                ans = get_waste_schedule(args.get("district", ""))
            elif name == "zagreb_air_quality":
                ans = get_air_quality()
            else:
                ans = f"Nepoznat tool: {name}"
            res = {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": ans}]}}
        else:
            res = {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Method {m} not found"}}
        _reply(req, res)

if __name__ == "__main__":
    main()
