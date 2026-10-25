#!/usr/bin/env python3
"""photovideo_mcp.py - Photography, Videography, RAW formats, Exposure, and Storyboarding MCP server."""
import sys
import json
import math

LOG_PROFILES = {
    "s-log3": {
        "maker": "Sony (A7S III, FX3, A7 IV, FX6)",
        "base_iso": "Native Base ISO 800 / Secondary Base ISO 12800 (CineEI / Flexible ISO)",
        "gamma_curve": "Quasi-logarithmic; preserves up to 15+ stops of dynamic range.",
        "exposure_rule": "Expose +1.0 to +1.7 EV over neutral grey. Middle grey sits at 41% IRE, 90% white reflector at 61% IRE.",
        "monitoring": "Use s709 or standard Rec.709 Gamma Display Assist to avoid underexposing shadows (which introduces chroma noise)."
    },
    "c-log3": {
        "maker": "Canon (EOS R5, R5 C, C70, C300 Mk III)",
        "base_iso": "Native Base ISO 800",
        "gamma_curve": "Designed for easy grading; tighter shadow roll-off than C-Log2 with clean low-noise shadows.",
        "exposure_rule": "Expose +0.5 to +1.0 EV over. Middle grey at 35% IRE, 90% white at 68% IRE.",
        "monitoring": "Canon View Assist Rec.709."
    },
    "d-log": {
        "maker": "DJI (Mavic 3 Pro, Inspire 3, Ronin 4D)",
        "base_iso": "Native Base ISO 400 (or ISO 800 in D-Log M 10-bit)",
        "gamma_curve": "Flat logarithmic curve preserving highlights in high-contrast outdoor aerial footage.",
        "exposure_rule": "Expose to the right (ETTR) using zebra lines at 95% to avoid clipping clouds or sunlight reflections.",
        "monitoring": "Use DJI official D-Log to Rec.709 3D LUT."
    },
    "v-log": {
        "maker": "Panasonic Lumix (S5 II, GH6, S1H)",
        "base_iso": "Native Base ISO 640",
        "gamma_curve": "V-Log / V-Gamut covering wider color space than BT.2020.",
        "exposure_rule": "Middle grey at 42% IRE, 90% white at 61% IRE.",
        "monitoring": "V-Log View Assist with official Panasonic V-Log to V-709 LUT."
    }
}

SHOT_TYPES = {
    "els": {"name": "Extreme Long Shot", "purpose": "Establish vast geography, scale, environment, or isolation. Subject is tiny or barely visible."},
    "ls": {"name": "Long Shot / Wide Shot", "purpose": "Shows full human body head-to-toe and immediate physical surroundings. Establishes character orientation and blocking."},
    "ms": {"name": "Medium Shot", "purpose": "Framed from waist up. Standard conversational framing for human dialogue, body language, and natural interaction."},
    "mcu": {"name": "Medium Close-Up", "purpose": "Framed from chest up. Focuses audience attention on emotional subtext while keeping character grounded in location."},
    "cu": {"name": "Close-Up", "purpose": "Framed from neck to top of head. Emphasizes facial expressions, psychological reactions, and subtle glances."},
    "ecu": {"name": "Extreme Close-Up", "purpose": "Magnifies eyes, lips, or a critical prop detail (key in lock, countdown timer) for dramatic punctuation."},
    "ots": {"name": "Over The Shoulder", "purpose": "Frames conversational depth between two actors, adhering strictly to the 180-degree axis of action."},
    "dutch": {"name": "Dutch Angle / Canted Frame", "purpose": "Tilted camera axis (15°-45°) conveying disorientation, psychological tension, unease, or danger."}
}

def calculate_exposure(shutter_speed: str, aperture: float, iso: int, target_fps: int = 24) -> str:
    try:
        # Standard 180-degree shutter rule for video
        rec_shutter = f"1/{target_fps * 2}s"
        # Calculate EV (Exposure Value at ISO 100)
        # EV = log2(N^2 / t) where N = aperture, t = time
        if "/" in shutter_speed:
            num, den = shutter_speed.split("/")
            t = float(num) / float(den.replace("s", ""))
        else:
            t = float(shutter_speed.replace("s", ""))
        
        ev100 = math.log2((aperture ** 2) / t) - math.log2(iso / 100)
        
        lines = [
            "## Exposure & Cinematic Parameters",
            f"- **Current Settings:** f/{aperture} | {shutter_speed} | ISO {iso}",
            f"- **Calculated EV (approx):** {ev100:.1f} EV",
            f"- **180° Video Shutter Rule (for {target_fps} fps):** Optimal shutter speed is **{rec_shutter}** for natural cinematic motion blur.",
            "\n### Neutral Density (ND) Recommendation:",
            "- If shooting outdoors in bright sun (f/2.8, 1/50s, Base ISO 800 Log): you will need a **4 to 6-stop ND filter** (ND16 to ND64) to maintain the 180° shutter rule without stopping down aperture."
        ]
        return "\n".join(lines)
    except Exception as e:
        return f"Exposure calculation error: {e}"

def lookup_log(profile: str) -> str:
    p = profile.lower().strip()
    for k, v in LOG_PROFILES.items():
        if k in p or p in k:
            lines = [f"## Camera Log Profile: {k.upper()} ({v['maker']})"]
            for prop, val in v.items():
                if prop != "maker":
                    lines.append(f"- **{prop.replace('_', ' ').title()}:** {val}")
            return "\n".join(lines)
    return f"Log profile '{profile}' not found. Supported profiles: {', '.join(LOG_PROFILES.keys())}."

def lookup_shot(shot_code: str) -> str:
    s = shot_code.lower().strip()
    for k, v in SHOT_TYPES.items():
        if k == s or k in s or s in v["name"].lower():
            return f"## Storyboard Shot: {v['name']} (`{k.upper()}`)\n- **Dramatic Purpose & Blocking:** {v['purpose']}\n- **Framing Guide:** Maintain consistent eye-line and follow the 180-degree rule across cuts."
    return f"Shot type '{shot_code}' not found. Supported shot codes: {', '.join(SHOT_TYPES.keys())} (e.g. ELS, Wide, MCU, CU, OTS, Dutch)."

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
            res = {"jsonrpc": "2.0", "id": mid, "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "photovideo-mcp", "version": "1.0.0"}}}
        elif m == "tools/list":
            tools = [
                {
                    "name": "exposure_calc",
                    "description": "Calculate exposure values (EV), 180-degree cinematic shutter rules, and ND filter requirements for photography and video.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "shutter_speed": {"type": "string", "description": "Shutter speed, e.g. '1/50', '1/100', '1/1000'"},
                            "aperture": {"type": "number", "description": "Aperture f-number, e.g. 1.8, 2.8, 4.0, 8.0"},
                            "iso": {"type": "integer", "description": "ISO value, e.g. 100, 400, 800, 3200"},
                            "target_fps": {"type": "integer", "default": 24, "description": "Target video frame rate (fps)"}
                        },
                        "required": ["shutter_speed", "aperture", "iso"]
                    }
                },
                {
                    "name": "log_profile_guide",
                    "description": "Look up camera Log profiles (Sony S-Log3, Canon C-Log3, DJI D-Log, Panasonic V-Log), native base ISOs, and exposure/IRE guidelines.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "profile": {"type": "string", "description": "Profile name: S-Log3, C-Log3, D-Log, V-Log"}
                        },
                        "required": ["profile"]
                    }
                },
                {
                    "name": "storyboard_shot_guide",
                    "description": "Look up storyboard framing shot types, dramatic purposes, and camera grammar (Wide, MCU, Close-Up, OTS, Dutch angle).",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "shot_type": {"type": "string", "description": "Shot type or code: ELS, LS, MS, MCU, CU, ECU, OTS, Dutch"}
                        },
                        "required": ["shot_type"]
                    }
                }
            ]
            res = {"jsonrpc": "2.0", "id": mid, "result": {"tools": tools}}
        elif m == "tools/call":
            params = req.get("params", {})
            name = params.get("name")
            args = params.get("arguments", {})
            if name == "exposure_calc":
                text = calculate_exposure(args.get("shutter_speed", "1/50"), float(args.get("aperture", 2.8)), int(args.get("iso", 800)), int(args.get("target_fps", 24)))
            elif name == "log_profile_guide":
                text = lookup_log(args.get("profile", ""))
            elif name == "storyboard_shot_guide":
                text = lookup_shot(args.get("shot_type", ""))
            else:
                text = f"Unknown tool: {name}"
            res = {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": text}]}}
        else:
            res = {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "Method not found"}}
        sys.stdout.write(json.dumps(res) + "\n")
        sys.stdout.flush()

if __name__ == "__main__":
    main()
