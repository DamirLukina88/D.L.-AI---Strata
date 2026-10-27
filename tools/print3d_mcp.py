#!/usr/bin/env python3
"""print3d_mcp.py - Free 3D Printing, Klipper/RepRap G-code, and Filament Presets MCP server."""
import sys
import json
import urllib.request
import urllib.parse
import re

KLIPPER_DOCS_BASE = "https://raw.githubusercontent.com/Klipper3d/klipper/master/docs/G-Codes.md"
BAMBU_PRESETS_BASE = "https://raw.githubusercontent.com/bambulab/BambuStudio/master/resources/profiles/BBL/filament"

def lookup_gcode(code: str) -> str:
    try:
        c = code.strip().upper()
        # Direct fetch from Klipper official documentation
        req = urllib.request.Request(KLIPPER_DOCS_BASE, headers={"User-Agent": "DL-AI-Strata/1.0"})
        with urllib.request.urlopen(req, timeout=12) as r:
            text = r.read().decode("utf-8", errors="ignore")
        
        # Search for section
        pattern = re.compile(rf"(###?\s+`?{re.escape(c)}`?.*?\n)(.*?)(?=\n###?|\Z)", re.DOTALL | re.IGNORECASE)
        match = pattern.search(text)
        if match:
            return f"## G-code / Macro: {c}\n\n{match.group(1)}\n{match.group(2)[:2000]}\n\n**Source:** Klipper G-Codes Official Documentation"
        
        # Fallback to RepRap wiki summary
        return f"G-code `{c}` not found in Klipper primary reference. Standard RepRap reference link: https://reprap.org/wiki/G-code#{c}"
    except Exception as e:
        return f"G-code lookup error: {e}"

def lookup_filament(vendor: str = "Bambu", material: str = "PLA") -> str:
    # Common engineering preset specs
    presets = {
        "pla": {
            "nozzle_temp": "210 - 230 °C",
            "bed_temp": "55 - 65 °C",
            "max_volumetric_speed": "21 - 24 mm³/s (High Flow)",
            "fan_speed": "100%",
            "chamber_temp": "Room temp (door/lid open on enclosed printers)",
            "retraction": "0.8 mm (direct drive) / 30 mm/s",
            "notes": "Optimal for general prototyping, stiff, low shrinkage. Susceptible to heat creep in hot chambers."
        },
        "petg": {
            "nozzle_temp": "240 - 260 °C",
            "bed_temp": "70 - 80 °C",
            "max_volumetric_speed": "14 - 18 mm³/s",
            "fan_speed": "40 - 60% (higher for overhangs)",
            "chamber_temp": "Room temp or enclosed",
            "retraction": "1.0 mm (direct drive) / 30 mm/s",
            "notes": "Tough, high chemical resistance, good layer adhesion. Needs dry filament (stringing prone)."
        },
        "abs": {
            "nozzle_temp": "250 - 270 °C",
            "bed_temp": "90 - 105 °C",
            "max_volumetric_speed": "16 - 20 mm³/s",
            "fan_speed": "0 - 20%",
            "chamber_temp": "45 - 60 °C (Enclosure mandatory)",
            "retraction": "0.8 mm / 35 mm/s",
            "notes": "High heat resistance, impact resistance, acetone vapor smoothable. Warps severely without enclosure."
        },
        "tpu": {
            "nozzle_temp": "220 - 240 °C",
            "bed_temp": "35 - 50 °C",
            "max_volumetric_speed": "3.5 - 6.0 mm³/s (Slow print speed mandatory)",
            "fan_speed": "80 - 100%",
            "chamber_temp": "Room temp",
            "retraction": "0.4 mm / 15 mm/s",
            "notes": "Flexible elastomer. Do not feed through Bambu AMS (direct spool holder only). Disable high retraction."
        },
        "pa-cf": {
            "nozzle_temp": "280 - 300 °C",
            "bed_temp": "95 - 110 °C",
            "max_volumetric_speed": "12 - 16 mm³/s",
            "fan_speed": "20 - 40%",
            "chamber_temp": "50 - 65 °C",
            "retraction": "0.8 mm / 30 mm/s",
            "notes": "Carbon fiber reinforced Nylon. Extremely abrasive: hardened steel nozzle and extruder gear required. Must dry at 80°C for 8h."
        }
    }
    key = material.lower().replace(" ", "").replace("-", "")
    for k, v in presets.items():
        if k in key or key in k:
            out = [f"## Filament Preset: {vendor.title()} {material.upper()}"]
            for prop, val in v.items():
                out.append(f"- **{prop.replace('_', ' ').title()}:** {val}")
            return "\n".join(out)
    return f"Preset for {material} not pre-cached. Reference Bambu Studio / PrusaSlicer official profile repository: https://github.com/bambulab/BambuStudio"

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
            res = {"jsonrpc": "2.0", "id": mid, "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "print3d-mcp", "version": "1.0.0"}}}
        elif m == "tools/list":
            tools = [
                {
                    "name": "gcode_lookup",
                    "description": "Look up Klipper and RepRap G-code command specifications, parameters, and macro behavior.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "code": {"type": "string", "description": "G-code command, e.g. G28, G29, M104, M109, BED_MESH_CALIBRATE"}
                        },
                        "required": ["code"]
                    }
                },
                {
                    "name": "filament_preset_lookup",
                    "description": "Look up Bambu Lab & Prusa filament printing parameters (temps, volumetric flow, cooling, enclosure requirements).",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "material": {"type": "string", "description": "Material type: PLA, PETG, ABS, TPU, PA-CF, PC"},
                            "vendor": {"type": "string", "default": "Bambu"}
                        },
                        "required": ["material"]
                    }
                }
            ]
            res = {"jsonrpc": "2.0", "id": mid, "result": {"tools": tools}}
        elif m == "tools/call":
            params = req.get("params", {})
            name = params.get("name")
            args = params.get("arguments", {})
            if name == "gcode_lookup":
                text = lookup_gcode(args.get("code", ""))
            elif name == "filament_preset_lookup":
                text = lookup_filament(args.get("vendor", "Bambu"), args.get("material", "PLA"))
            else:
                text = f"Unknown tool: {name}"
            res = {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": text}]}}
        else:
            res = {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "Method not found"}}
        _reply(req, res)

if __name__ == "__main__":
    main()
