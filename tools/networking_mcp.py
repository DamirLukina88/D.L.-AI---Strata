#!/usr/bin/env python3
"""networking_mcp.py - LAN, Optin/Fiber SFP/QSFP, Ethernet pinouts, PoE, and IEEE MAC lookup MCP server."""
import sys
import json
import urllib.request
import urllib.parse
import re

OPTICS_GUIDE = {
    "sfp": "1 Gbps small form-factor pluggable transceiver.",
    "sfp+": "10 Gbps optical transceiver (SFP Plus). Backward compatible with SFP slots if switch port supports 1G.",
    "sfp28": "25 Gbps optical transceiver. Common in modern data centers and high-speed enterprise top-of-rack switches.",
    "qsfp+": "40 Gbps transceiver (Quad SFP). 4 x 10G lanes. Can break out to 4x SFP+ via MPO/MTP breakout cable.",
    "qsfp28": "100 Gbps transceiver. 4 x 25G lanes. Can break out to 4x SFP28."
}

FIBER_TYPES = {
    "om3": "Multi-Mode Fiber (Aqua jacket). 850nm wavelength (VCSEL). Up to 10 Gbps up to 300 meters.",
    "om4": "Multi-Mode Fiber (Violet/Aqua jacket). 850nm wavelength. Up to 10 Gbps up to 400m, 40G/100G up to 150m.",
    "os2": "Single-Mode Fiber (Yellow jacket). 1310nm / 1550nm wavelength. Long-range up to 10km - 40km+ with LR/ER optics."
}

def lookup_optics(query: str) -> str:
    q = query.lower().strip()
    lines = ["## Optical Transceiver & Fiber Standards Guide\n"]
    matched = False
    for k, v in OPTICS_GUIDE.items():
        if k in q:
            lines.append(f"- **{k.upper()}:** {v}")
            matched = True
    for k, v in FIBER_TYPES.items():
        if k in q:
            lines.append(f"- **{k.upper()}:** {v}")
            matched = True
    if not matched:
        lines.append("### Common Form Factors:")
        for k, v in OPTICS_GUIDE.items():
            lines.append(f"- **{k.upper()}:** {v}")
        lines.append("\n### Fiber Media Standards:")
        for k, v in FIBER_TYPES.items():
            lines.append(f"- **{k.upper()}:** {v}")
    lines.append("\n- **DAC Cables:** Direct Attach Copper (passive twinax) for short in-rack switch-to-server interconnects (< 3-5m), zero optical latency and low power.")
    return "\n".join(lines)

def lookup_cabling(standard: str = "t568b") -> str:
    s = standard.lower().strip()
    if "a" in s and "b" not in s:
        pinout = ["1: White/Green", "2: Green", "3: White/Orange", "4: Blue", "5: White/Blue", "6: Orange", "7: White/Brown", "8: Brown"]
        name = "T568A"
    else:
        pinout = ["1: White/Orange", "2: Orange", "3: White/Green", "4: Blue", "5: White/Blue", "6: Green", "7: White/Brown", "8: Brown"]
        name = "T568B (Commercial & Residential Default)"
    
    lines = [
        f"## RJ45 Ethernet Cabling Standard: {name}",
        "Pin assignments (looking at the bottom of the RJ45 plug with clip facing down/away):",
        *[f"  • Pin {p}" for p in pinout],
        "\n### Ethernet Categories & Bandwidth:",
        "- **Cat5e:** Up to 1 Gbps up to 100m (supports 2.5 Gbps Multi-Gig over short runs).",
        "- **Cat6:** Up to 10 Gbps up to 55m; 1 Gbps up to 100m.",
        "- **Cat6A:** Full 10 Gbps up to 100m (shielded or unshielded).",
        "\n### Power over Ethernet (PoE):",
        "- **802.3af (PoE):** 15.4W at switch (12.95W at device).",
        "- **802.3at (PoE+):** 30.0W at switch (25.5W at device).",
        "- **802.3bt (PoE++ Type 3 / Type 4):** 60W / 90W for PTZ cameras and high-draw APs."
    ]
    return "\n".join(lines)

def lookup_mac_vendor(mac: str) -> str:
    try:
        clean = re.sub(r"[^0-9A-Fa-f]", "", mac)[:6].upper()
        if len(clean) < 6:
            return f"Please provide at least the first 6 hex characters of the MAC address (OUI prefix), e.g. '00:1A:2B'."
        formatted = f"{clean[:2]}:{clean[2:4]}:{clean[4:6]}"
        url = f"https://api.macvendors.com/{urllib.parse.quote(formatted)}"
        req = urllib.request.Request(url, headers={"User-Agent": "DL-AI-Strata/1.0"})
        with urllib.request.urlopen(req, timeout=6) as r:
            vendor = r.read().decode("utf-8")
        return f"## MAC Vendor Lookup: `{mac}`\n- **OUI Prefix:** `{formatted}`\n- **Manufacturer / Vendor:** **{vendor}**"
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return f"MAC prefix `{mac}` not found in IEEE OUI database."
        return f"MAC lookup error: {e}"
    except Exception as e:
        return f"MAC query error: {e}"

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
            res = {"jsonrpc": "2.0", "id": mid, "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "networking-mcp", "version": "1.0.0"}}}
        elif m == "tools/list":
            tools = [
                {
                    "name": "optics_guide",
                    "description": "Look up fiber optic and SFP/SFP+/SFP28/QSFP transceiver standards, wavelengths (850nm vs 1310nm), and OM3/OM4/OS2 fiber media.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Form factor or fiber type: SFP, SFP+, QSFP28, OM3, OM4, OS2, DAC", "default": "sfp+"}
                        }
                    }
                },
                {
                    "name": "cabling_pinout",
                    "description": "Look up RJ45 Ethernet pinout color codes (T568A vs T568B), Cat5e/6/6A bandwidth, and PoE wattage standards.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "standard": {"type": "string", "enum": ["t568a", "t568b"], "default": "t568b"}
                        }
                    }
                },
                {
                    "name": "mac_vendor_lookup",
                    "description": "Identify network hardware manufacturer/vendor from device MAC address or OUI prefix (e.g. 00:11:22).",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "mac": {"type": "string", "description": "MAC address or prefix (e.g. '00:1A:2B:3C:4D:5E' or '001A2B')"}
                        },
                        "required": ["mac"]
                    }
                }
            ]
            res = {"jsonrpc": "2.0", "id": mid, "result": {"tools": tools}}
        elif m == "tools/call":
            params = req.get("params", {})
            name = params.get("name")
            args = params.get("arguments", {})
            if name == "optics_guide":
                text = lookup_optics(args.get("query", "sfp+"))
            elif name == "cabling_pinout":
                text = lookup_cabling(args.get("standard", "t568b"))
            elif name == "mac_vendor_lookup":
                text = lookup_mac_vendor(args.get("mac", ""))
            else:
                text = f"Unknown tool: {name}"
            res = {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": text}]}}
        else:
            res = {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "Method not found"}}
        sys.stdout.write(json.dumps(res) + "\n")
        sys.stdout.flush()

if __name__ == "__main__":
    main()
