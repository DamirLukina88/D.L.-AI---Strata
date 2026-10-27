#!/usr/bin/env python3
"""drones_mcp.py - Drones, DJI hardware specs, EASA/CCAA Croatian drone regulations, and AMC Portal airspace."""
import sys
import json

DJI_MODELS = {
    "mini 4 pro": {
        "weight": "249 g",
        "easa_class": "C0 (< 250 g)",
        "camera": "1/1.3\" CMOS, 48MP, 4K/60fps HDR, 4K/100fps Slow-mo, D-Log M (10-bit)",
        "transmission": "DJI O4 (OcuSync 4), up to 10 km (CE) / 20 km (FCC)",
        "obstacle_avoidance": "Omnidirectional obstacle sensing (APAS 5.0)",
        "wind_resistance": "10.7 m/s (Scale 5)",
        "flight_time": "Up to 34 mins (Standard Battery)",
        "ccaa_rules": "Open Category A1. Can fly over uninvolved people (no crowds). Pilot registration mandatory on CCAA UAS portal (because of camera). Online exam A1/A3 recommended."
    },
    "mini 3 pro": {
        "weight": "249 g",
        "easa_class": "C0 (< 250 g) / Legacy under 250g",
        "camera": "1/1.3\" CMOS, 48MP, 4K/60fps, D-Cinelike (10-bit)",
        "transmission": "DJI O3, up to 8 km (CE)",
        "obstacle_avoidance": "Tri-directional (forward, backward, downward)",
        "wind_resistance": "10.7 m/s",
        "flight_time": "Up to 34 mins",
        "ccaa_rules": "Open Category A1. Pilot registration mandatory. Safe for residential flights under 120m AGL."
    },
    "air 3": {
        "weight": "720 g",
        "easa_class": "C1 (< 900 g)",
        "camera": "Dual Primary Cameras: 1/1.3\" 24mm Wide + 70mm 3x Medium Telephoto, 4K/60fps HDR, 10-bit D-Log M",
        "transmission": "DJI O4, up to 10 km (CE)",
        "obstacle_avoidance": "Omnidirectional (APAS 5.0)",
        "wind_resistance": "12 m/s (Scale 6)",
        "flight_time": "Up to 46 mins",
        "ccaa_rules": "Open Category A1. Operator registration mandatory. Mandatory A1/A3 online competency certificate. Cannot intentionally fly over uninvolved people."
    },
    "mavic 3 pro": {
        "weight": "958 g",
        "easa_class": "C2 (< 4 kg)",
        "camera": "Triple Camera: 4/3 CMOS Hasselblad 24mm (Apple ProRes 422 HQ / D-Log), 70mm Medium Tele, 166mm Tele",
        "transmission": "DJI O3+, up to 8 km (CE)",
        "obstacle_avoidance": "Omnidirectional (APAS 5.0)",
        "wind_resistance": "12 m/s",
        "flight_time": "Up to 43 mins",
        "ccaa_rules": "Open Category A2 (or A3). Requires A1/A3 certificate + A2 theoretical proctored exam. Must maintain 50m lateral distance from uninvolved people (30m in low-speed mode)."
    }
}

def lookup_dji(model: str) -> str:
    m = model.lower().strip()
    for k, v in DJI_MODELS.items():
        if k in m or m in k:
            lines = [f"## DJI Drone: {k.title()}"]
            for prop, val in v.items():
                lines.append(f"- **{prop.replace('_', ' ').title()}:** {val}")
            return "\n".join(lines)
    return f"Drone model '{model}' not found in database. Supported models: Mini 4 Pro, Mini 3 Pro, Air 3, Mavic 3 Pro."

def croatia_regulations(category: str = "open") -> str:
    return (
        "## Pravila za upravljanje dronovima u Republici Hrvatskoj (CCAA & EASA)\n\n"
        "### 1. Registracija operatera (Obavezno za sve dronove s kamerom):\n"
        "- **Portal:** Registracija se vrši na portalu **Hrvatske agencije za civilno zrakoplovstvo (CCAA)**: https://www.ccaa.hr\n"
        "- **Operator ID:** Nakon registracije dobivate jedinstveni broj operatera koji mora biti fizički istaknut na dronu (naljepnica).\n"
        "- **Osiguranje:** Obavezno osiguranje od odgovornosti prema trećima za dronove mase iznad 250 g.\n\n"
        "### 2. EASA Otvorena kategorija (Open Category):\n"
        "- **Potkategorija A1 (Dronovi < 900g, npr. Mini serija C0, Air serija C1):**\n"
        "  • C0 (<250g): Let iznad pojedinačnih prolaznika dopušten (nikada iznad skupova ljudi).\n"
        "  • C1 (<900g): Let iznad ljudi nije dopušten (u slučaju neočekivanog preleta odmah se udaljiti).\n"
        "  • Ispit: Besplatan online ispit za potkategorije A1/A3 na stranicama CCAA.\n"
        "- **Potkategorija A2 (Dronovi < 4kg s oznakom C2, npr. Mavic 3 Pro):**\n"
        "  • Udaljenost: Minimalno 50 m od ljudi (ili 30 m uz uključen low-speed način rada).\n"
        "  • Ispit: A2 ispit osposobljenosti u prostorijama CCAA ili ovlaštenog ispitnog centra.\n"
        "- **Maksimalna visina:** Uvijek do **120 m iznad razine tla (AGL)** u vidnom polju (VLOS).\n\n"
        "### 3. Zračni prostor i odobrenje leta (AMC Portal - HKZP):\n"
        "- **Hrvatska kontrola zračne plovidbe (Croatia Control):** https://amc.crocontrol.hr\n"
        "- **Aplikacija AMC Portal Mobile:** Za svaki let u kontroliranom zračnom prostoru (npr. **CTR Zagreb - LDZA**) obavezna je rezervacija zračnog prostora putem mobilne aplikacije neposredno prije leta (automatizirano odobrenje za visine do 50m AGL).\n"
        "- **Zabrane:** Strogo zabranjen let iznad vojnih objekata, nacionalnih parkova (bez posebne dozvole uprave parka) i u zoni aerodroma bez odobrenja kontrole leta."
    )

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
            res = {"jsonrpc": "2.0", "id": mid, "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "drones-mcp", "version": "1.0.0"}}}
        elif m == "tools/list":
            tools = [
                {
                    "name": "dji_drone_specs",
                    "description": "Look up DJI drone specifications, camera capabilities, transmission systems (O3/O4), wind resistance, and EASA class mark.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "model": {"type": "string", "description": "DJI drone model, e.g. 'Mini 4 Pro', 'Air 3', 'Mavic 3 Pro'"}
                        },
                        "required": ["model"]
                    }
                },
                {
                    "name": "croatia_drone_rules",
                    "description": "Službena pravila za letenje dronova u Hrvatskoj (CCAA, EASA A1/A2/A3 kategorije, AMC Portal aplikacija, registracija operatera i visinska ograničenja).",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "category": {"type": "string", "default": "open", "description": "Kategorija leta (open, A1, A2, AMC)"}
                        }
                    }
                }
            ]
            res = {"jsonrpc": "2.0", "id": mid, "result": {"tools": tools}}
        elif m == "tools/call":
            params = req.get("params", {})
            name = params.get("name")
            args = params.get("arguments", {})
            if name == "dji_drone_specs":
                text = lookup_dji(args.get("model", ""))
            elif name == "croatia_drone_rules":
                text = croatia_regulations(args.get("category", "open"))
            else:
                text = f"Unknown tool: {name}"
            res = {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": text}]}}
        else:
            res = {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "Method not found"}}
        _reply(req, res)

if __name__ == "__main__":
    main()
