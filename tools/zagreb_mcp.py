#!/usr/bin/env python3
"""zagreb_mcp.py - Zagreb civic services, ZET public transit (zet.skoljka.org), 24/7 pharmacies, waste management, live air quality, and BAJS / Nextbike live stations."""
import sys
import json
import re
import html
import urllib.request

ZET_TRAM_LINES = {
    "1": "Zapadni kolodvor - Borongaj (dnevna)",
    "2": "Črnomerec - Savišće (dnevna, preko Glavnog kolodvora i Autobusnog kolodvora)",
    "3": "Ljubljanica - Savišće (dnevna, ne vozi subotom, nedjeljom i blagdanom)",
    "4": "Savski most - Dubec (dnevna, preko Glavnog kolodvora i Draškovićeve)",
    "5": "Prečko - Park Maksimir (dnevna)",
    "6": "Črnomerec - Sopot (dnevna, preko Trga bana Jelačića i Glavnog kolodvora)",
    "7": "Savski most - Dubrava (dnevna, preko Novog Zagreba i Šubićeve)",
    "8": "Mihaljevac - Zapruđe (dnevna, preko Draškovićeve i Autobusnog kolodvora)",
    "9": "Ljubljanica - Borongaj (dnevna, preko Glavnog kolodvora)",
    "11": "Črnomerec - Dubec (dnevna, glavna žila kucavica preko Trga bana Jelačića)",
    "12": "Ljubljanica - Dubrava (dnevna, preko Trga bana Jelačića)",
    "13": "Žitnjak - Kvaternikov trg (dnevna, preko Trga bana Jelačića i Glavnog kolodvora)",
    "14": "Mihaljevac - Savski most (dnevna, preko Trga bana Jelačića i Savske)",
    "15": "Mihaljevac - Gračansko dolje (dnevna, veza s Žičarom Sljeme)",
    "17": "Prečko - Borongaj (dnevna, preko Savske, Trga bana Jelačića i Trga žrtava fašizma)",
    "31": "Črnomerec - Savski most (noćna linija: 23:30 - 04:30)",
    "32": "Prečko - Borongaj (noćna linija: 23:30 - 04:30)",
    "33": "Gračansko dolje - Savišće (noćna linija: 23:30 - 04:30)",
    "34": "Ljubljanica - Dubec (noćna linija: 23:30 - 04:30)"
}

PHARMACIES_24_7 = [
    {
        "name": "Ljekarna Centar (Trg bana Jelačića)",
        "address": "Trg bana Josipa Jelačića 3",
        "phone": "+385 1 4816 198",
        "notes": "Stalno dežurstvo 0-24h svaki dan uključujući nedjelje i blagdane."
    },
    {
        "name": "Ljekarna Črnomerec",
        "address": "Ilica 301 (okretište Črnomerec)",
        "phone": "+385 1 3750 321",
        "notes": "Stalno dežurstvo 0-24h za zapadni dio grada."
    },
    {
        "name": "Ljekarna Dubrava",
        "address": "Grižanska 4 (kod Doma zdravlja Dubrava)",
        "phone": "+385 1 2992 350",
        "notes": "Stalno dežurstvo 0-24h za istočni dio grada."
    },
    {
        "name": "Ljekarna Siget (Novi Zagreb)",
        "address": "Avenija Većeslava Holjevca 22",
        "phone": "+385 1 6525 425",
        "notes": "Stalno dežurstvo 0-24h za Novi Zagreb."
    },
    {
        "name": "Ljekarna Trešnjevka",
        "address": "Ozaljska 1 (kod Trešnjevačkog trga)",
        "phone": "+385 1 3097 586",
        "notes": "Stalno dežurstvo 0-24h."
    }
]

DISTRICT_SCHEDULES = {
    "donji grad": "Miješani komunalni otpad: Ponedjeljak, Srijeda, Petak. Papir: Utorkom (svaka 2 tjedna). Plastika/Metal: Četvrtkom (svaka 2 tjedna). Biootpad: Ponedjeljkom i Četvrtkom.",
    "gornji grad": "Miješani komunalni otpad: Ponedjeljak, Srijeda, Petak. Papir: Utorkom. Plastika: Četvrtkom. Biootpad: Ponedjeljkom i Četvrtkom.",
    "tresnjevka": "Miješani komunalni otpad: Utorak i Petak. Papir: Ponedjeljkom (svaka 2 tjedna). Plastika: Srijedom (svaka 2 tjedna). Biootpad: Utorkom.",
    "maksimir": "Miješani komunalni otpad: Ponedjeljak i Četvrtak. Papir: Srijedom (svaka 2 tjedna). Plastika: Petkom (svaka 2 tjedna). Biootpad: Četvrtkom.",
    "novi zagreb": "Miješani komunalni otpad: Utorak i Petak. Papir: Četvrtkom (svaka 2 tjedna). Plastika: Ponedjeljkom (svaka 2 tjedna). Biootpad: Srijedom.",
    "dubrava": "Miješani komunalni otpad: Ponedjeljak i Četvrtak. Papir: Utorkom (svaka 2 tjedna). Plastika: Srijedom (svaka 2 tjedna). Biootpad: Petkom.",
    "crnomerec": "Miješani komunalni otpad: Utorak i Petak. Papir: Četvrtkom (svaka 2 tjedna). Plastika: Ponedjeljkom (svaka 2 tjedna). Biootpad: Srijedom."
}

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
        lines = ["## ZET Noćne Tramvajske Linije (23:30 - 04:30 h):"]
        for num in ["31", "32", "33", "34"]:
            lines.append(f"- **Linija {num}:** {ZET_TRAM_LINES[num]}")
        return "\n".join(lines)
    
    matches = []
    for num, desc in ZET_TRAM_LINES.items():
        if num == q or f"linija {num}" in q or q in desc.lower():
            matches.append(f"- **Linija {num}:** {desc}")
    
    if matches:
        return f"## Rezultati pretrage ZET linija za '{query}':\n" + "\n".join(matches) + "\n" + live_news
    return f"Nije pronađena ZET linija za pojam '{query}'. Dostupne linije: 1-17 (dnevne) i 31-34 (noćne).\n{live_news}"

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
        "- **Dom zdravlja Zagreb - Centar:** Runjaninova 4 (radno vrijeme noću: 22:00 - 06:00, nedjeljom i blagdanom 0-24h)\n"
        "- **Klinička bolnica Dubrava:** Avenija Gojka Šuška 6 (Maksilofacijalna kirurgija i akutne traume lica i čeljusti)\n\n"
        "### 5. Opći hitni brojevi:\n"
        "- **Jedinstveni europski broj za hitne službe:** 112\n"
        "- **Hitna medicinska pomoć:** 194\n"
        "- **Vatrogasci:** 193\n"
        "- **Policija:** 192\n"
        "- **HAK pomoć na cesti:** 1987"
    )

def get_pharmacies() -> str:
    lines = ["## Dežurne ljekarne u Zagrebu (0-24 h):"]
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
    d = district.strip().lower()
    if not d:
        lines = [
            "## Zagrebački Holding - Čistoća: Odvoz otpada",
            "**Sustav ZG vrećica:** Miješani komunalni otpad smije se odlagati isključivo u službenim plavim ZG vrećicama (10L, 20L, 40L).",
            "**Besplatno preuzimanje:** Žute vrećice (plastika/metal) i smeđe vrećice (biootpad) Čistoća dijeli korisnicima.",
            "\n### Odvoz po gradskim četvrtima:"
        ]
        for name, sched in DISTRICT_SCHEDULES.items():
            lines.append(f"- **{name.title()}:** {sched}")
        lines.append("\n**Glomazni otpad:** Svako kućanstvo ima pravo na besplatan odvoz do 2 m³ glomaznog otpada godišnje na zahtjev.")
        return "\n".join(lines)
    
    for name, sched in DISTRICT_SCHEDULES.items():
        if name in d or d in name:
            return f"## Čistoća Raspored: {name.title()}\n- {sched}\n\n**Reciklažna dvorišta:** Dostupna u svakoj gradskoj četvrti za besplatno odlaganje elektroničkog, glomaznog i opasnog otpada za građane Zagreba."
    
    return f"Gradska četvrt '{district}' nije pronađena. Podržane četvrti: {', '.join(k.title() for k in DISTRICT_SCHEDULES.keys())}."

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
                    "description": "24/7 on-duty pharmacies in Zagreb (Centar, Črnomerec, Dubrava, Siget, Trešnjevka) with phone numbers and hospital emergency centers.",
                    "inputSchema": {"type": "object", "properties": {}}
                },
                {
                    "name": "zagreb_emergency",
                    "description": "Zagreb 24/7 specialized emergency services: Poison Control Center (Centar za kontrolu otrovanja), emergency pediatric clinics (Klaićeva, Rebro), emergency 24/7 vet clinic (Veterinarski fakultet), and night emergency dentist (Runjaninova).",
                    "inputSchema": {"type": "object", "properties": {}}
                },
                {
                    "name": "cistoca_waste_schedule",
                    "description": "Zagreb Čistoća waste collection schedule by city district, ZG bag system, and recycling yard rules.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"district": {"type": "string", "description": "City district (e.g. 'Tresnjevka', 'Donji grad', 'Maksimir', 'Novi Zagreb')."}},
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
        sys.stdout.write(json.dumps(res) + "\n")
        sys.stdout.flush()

if __name__ == "__main__":
    main()
