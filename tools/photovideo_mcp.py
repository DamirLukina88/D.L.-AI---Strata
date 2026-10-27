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

AUDIO_STANDARDS = {
    "youtube": {
        "platform": "YouTube",
        "target_lufs": "-14 LUFS (±1 LUFS)",
        "true_peak": "-1.0 dBFS (prevents inter-sample distortion after lossy Opus/AAC compression)",
        "notes": "YouTube automatically attenuates audio louder than -14 LUFS, but does NOT boost quieter audio."
    },
    "broadcast": {
        "platform": "European Broadcast / TV (EBU R128 / HRT)",
        "target_lufs": "-23 LUFS (±0.5 LUFS)",
        "true_peak": "-1.0 dBFS",
        "notes": "Standard for European television broadcast and film festival screeners."
    },
    "spotify": {
        "platform": "Spotify / Streaming Music",
        "target_lufs": "-14 LUFS",
        "true_peak": "-1.0 dBFS (-2.0 dBFS for loud masters)",
        "notes": "Standard music streaming normalization."
    },
    "podcasts": {
        "platform": "Podcasts / Dialogue / Spoken Word (Apple / Spotify)",
        "target_lufs": "-16 LUFS (stereo) / -19 LUFS (mono)",
        "true_peak": "-1.0 dBFS",
        "notes": "Optimal conversational dynamic range for headphones and car audio."
    }
}

MIC_PATTERNS = {
    "shotgun": {
        "pattern": "Supercardioid / Lobar Interference Tube (e.g. Sennheiser MKH416, Deity S-Mic 2, Rode NTG)",
        "best_for": "Boom mic boomed from 45° overhead pointing at actor's chest. High side rejection.",
        "gotcha": "Avoid in small untreated rooms with bare concrete/drywall; acoustic reflections cause severe comb filtering in the phase tube."
    },
    "lavalier": {
        "pattern": "Omnidirectional condenser (e.g. Rode Wireless PRO, DJI Mic 2, Sanken COS-11D)",
        "best_for": "Clip-on bodypack placed 15-20 cm (6-8 in) below mouth at mid-sternum. Natural head-turn consistency.",
        "gotcha": "Requires moleskin / vampire clip against clothing rustle, and high-density fur 'deadcat' outdoors against wind buffet."
    },
    "cardioid": {
        "pattern": "Cardioid (e.g. Shure SM7B, Rode Procaster)",
        "best_for": "Studio voiceover, untreated podcast booths, desk recording. Complete rear null at 180°.",
        "gotcha": "Pronounced proximity effect; maintain consistent 5-10 cm mouth distance."
    }
}

def audio_guide(topic: str = "") -> str:
    t = topic.lower().strip()
    lines = ["## Audio Engineering & Loudness Standards for Video"]
    
    # Check loudness
    lines.append("\n### 1. Platform Loudness Target Standards (LUFS):")
    for k, v in AUDIO_STANDARDS.items():
        lines.append(f"- **{v['platform']}:** Target: **{v['target_lufs']}** | True Peak: **{v['true_peak']}**\n  *{v['notes']}*")
    
    lines.append("\n### 2. Microphone Selection & Polar Patterns:")
    for k, v in MIC_PATTERNS.items():
        lines.append(f"- **{k.title()} ({v['pattern']}):**\n  • Best for: {v['best_for']}\n  • Warning: {v['gotcha']}")
        
    lines.append("\n### 3. Bit Depth & Sample Rates for Video:")
    lines.append("- **Standard Delivery:** **48 kHz / 24-bit PCM** (Cinema and broadcast universal standard; 44.1 kHz is for legacy CD music).")
    lines.append("- **32-Bit Float Recording:** Dual-ADC architecture providing ~1528 dB dynamic range. Physically impossible to clip digital preamp on actor screams or sudden explosions; normalizes instantly in post without distortion.")
    
    return "\n".join(lines)

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

def davinci_resolve_guide(camera_format: str = "") -> str:
    return (
        "## DaVinci Resolve CST (Color Space Transform) & Grading Workflow\n\n"
        "### 1. Recommended Color Management: DaVinci Wide Gamut (DWG)\n"
        "Working in **DaVinci Wide Gamut / Intermediate** provides 100% non-destructive grading with wider color volume than ARRI LogC3 or ACEScc.\n\n"
        "### 2. Node Graph Sandwich Setup:\n"
        "- **Node 1 [Input CST]:**\n"
        "  • **Sony:** Input Color Space: `Sony S-Gamut3.Cine` | Input Gamma: `Sony S-Log3`\n"
        "  • **Canon:** Input Color Space: `Canon Cinema Gamut` | Input Gamma: `Canon Log 3`\n"
        "  • **DJI:** Input Color Space: `DJI D-Gamut` | Input Gamma: `DJI D-Log` (or Rec.709 for D-Log M)\n"
        "  • **Output of Node 1:** Output Color Space: `DaVinci Wide Gamut` | Output Gamma: `DaVinci Intermediate`\n"
        "- **Nodes 2 to 5 [Grading in DWG Space]:**\n"
        "  • **Node 2 (Exposure):** Use Offset wheel in Primary Wheels (does not crush shadows or clip highlights in wide gamut).\n"
        "  • **Node 3 (White Balance):** Temp / Tint and RGB parade alignment.\n"
        "  • **Node 4 (Contrast & Pivot):** Custom S-curves or Contrast wheel with Pivot set to ~0.38 - 0.42.\n"
        "  • **Node 5 (Look / Creative):** Split-toning, film emulation LUTs, Hue vs Sat curves.\n"
        "- **Node 6 [Output CST]:**\n"
        "  • Input Color Space: `DaVinci Wide Gamut` | Input Gamma: `DaVinci Intermediate`\n"
        "  • Output Color Space: `Rec.709` | Output Gamma: `Gamma 2.4` (Standard web/master) or `Rec.709-A` (Apple QuickTime gamma bug fix)\n"
        "  • Tone Mapping: `DaVinci` | Saturation Compression: `Enabled`\n\n"
        "### 3. Essential Delivery & Export Settings (YouTube & Web):\n"
        "- **Format:** MP4 or QuickTime (.mov)\n"
        "- **Codec:** H.265 (HEVC) or Apple ProRes 422 HQ\n"
        "- **Advanced Settings:** Color Space Tag: `Rec.709` | Gamma Tag: `Rec.709` (or `Rec.709-A`)\n"
        "- **Audio Export:** 48,000 Hz, 24-bit Linear PCM (or AAC 320 kbps)\n\n"
        "### 4. Critical Productivity Shortcuts:\n"
        "- `Alt + S`: Append new Serial Node\n"
        "- `Alt + P`: Create Parallel Node\n"
        "- `Ctrl + D`: Bypass current Node\n"
        "- `Shift + D`: Bypass all color grades and fusion effects\n"
        "- `Shift + Up/Down`: Jump between clip timeline items\n"
        "- `Ctrl + Shift + W`: Toggle split screen comparison"
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
                },
                {
                    "name": "audio_engineering_guide",
                    "description": "Audio engineering for video: platform loudness standards (YouTube -14 LUFS, Broadcast -23 LUFS, Podcasts -16 LUFS, True Peak), microphone polar patterns (shotgun, lavalier, cardioid), and 32-bit float audio.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "topic": {"type": "string", "description": "Specific audio topic: 'lufs', 'youtube', 'broadcast', 'microphones', '32bit float' (omit for full guide)"}
                        },
                        "required": []
                    }
                },
                {
                    "name": "davinci_resolve_guide",
                    "description": "DaVinci Resolve Color Space Transform (CST) workflow (Sony S-Log3, Canon C-Log3, DJI D-Log to DaVinci Wide Gamut), node graph order, export presets, and shortcuts.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "camera_format": {"type": "string", "description": "Camera format (e.g. 'Sony', 'Canon', 'DJI')."}
                        },
                        "required": []
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
            elif name == "audio_engineering_guide":
                text = audio_guide(args.get("topic", ""))
            elif name == "davinci_resolve_guide":
                text = davinci_resolve_guide(args.get("camera_format", ""))
            else:
                text = f"Unknown tool: {name}"
            res = {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": text}]}}
        else:
            res = {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "Method not found"}}
        _reply(req, res)

if __name__ == "__main__":
    main()
