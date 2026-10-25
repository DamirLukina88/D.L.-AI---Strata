#!/usr/bin/env python3
"""electronics_mcp.py - Electronics, Components (LCSC/JLCPCB), SMD codes, and pinouts MCP server."""
import sys
import json
import urllib.request
import urllib.parse
import re

COMMON_PARTS = {
    "ne555": {"type": "Precision Timer", "package": "DIP-8 / SOIC-8", "voltage": "4.5V - 16V", "lcsc": "C46749", "desc": "Standard 555 timer IC for pulse generation and timing circuits."},
    "lm358": {"type": "Dual Operational Amplifier", "package": "SOP-8 / DIP-8", "voltage": "3V - 32V", "lcsc": "C7426", "desc": "Low-power dual op-amp, single or split supply."},
    "esp32-wroom-32e": {"type": "Wi-Fi + BT MCU Module", "package": "SMD-38", "voltage": "3.0V - 3.6V", "lcsc": "C701342", "desc": "Dual-core Xtensa LX6 MCU, 240MHz, 4MB SPI flash, PCB antenna."},
    "rp2040": {"type": "Dual ARM Cortex-M0+ MCU", "package": "QFN-56", "voltage": "1.8V - 3.3V", "lcsc": "C2040", "desc": "Raspberry Pi silicon, 133MHz, 264KB SRAM, Programmable I/O (PIO)."},
    "ams1117-3.3": {"type": "Linear Voltage Regulator (LDO)", "package": "SOT-223", "voltage": "Vin up to 15V, Vout 3.3V", "lcsc": "C6186", "desc": "1A low dropout positive voltage regulator, 3.3V fixed."},
    "2n7002": {"type": "N-Channel MOSFET", "package": "SOT-23", "voltage": "Vds 60V, Id 115mA", "lcsc": "C8545", "desc": "Small signal N-channel enhancement mode field-effect transistor."},
    "ch340c": {"type": "USB to Serial UART Bridge", "package": "SOP-16", "voltage": "3.3V - 5V", "lcsc": "C84681", "desc": "Built-in crystal oscillator USB-to-UART converter."},
    "ws2812b": {"type": "Addressable RGB LED", "package": "SMD-5050", "voltage": "3.7V - 5.3V", "lcsc": "C114586", "desc": "Intelligent control LED with integrated driver chip (NeoPixel)."}
}

def lookup_component(query: str) -> str:
    q = query.lower().strip()
    # Check pre-cached parts
    for k, v in COMMON_PARTS.items():
        if k in q or q in k:
            return (
                f"## Component: {k.upper()} ({v['type']})\n"
                f"- **Package / Footprint:** {v['package']}\n"
                f"- **Operating Voltage:** {v['voltage']}\n"
                f"- **LCSC Part #:** `{v['lcsc']}` (JLCPCB Basic/Preferred Part)\n"
                f"- **Description:** {v['desc']}\n"
                f"- **Datasheet & Stock:** https://www.lcsc.com/search?q={v['lcsc']}"
            )
    return f"Component '{query}' not in common cache. Search JLCPCB SMT / LCSC catalog at https://jlcpcb.com/parts/componentSearch?searchTxt={urllib.parse.quote(query)}"

def decode_smd_resistor(code: str) -> str:
    c = code.strip().upper()
    if re.match(r"^\d{3}$", c): # 3-digit: 102 -> 10 * 10^2 = 1k
        val = int(c[:2]) * (10 ** int(c[2]))
    elif re.match(r"^\d{4}$", c): # 4-digit: 1002 -> 100 * 10^2 = 10k
        val = int(c[:3]) * (10 ** int(c[3]))
    elif "R" in c:
        val = float(c.replace("R", "."))
    else:
        return f"Could not decode SMD code '{code}'. Supported formats: 3-digit (e.g. 103 = 10k), 4-digit (e.g. 4702 = 47k), or with R (e.g. 4R7 = 4.7Ω)."
    
    if val >= 1_000_000:
        formatted = f"{val/1_000_000:.2f} MΩ".rstrip("0").rstrip(".") + " MΩ"
    elif val >= 1_000:
        formatted = f"{val/1_000:.2f} kΩ".rstrip("0").rstrip(".") + " kΩ"
    else:
        formatted = f"{val} Ω"
    return f"## SMD Resistor Code `{code}`\n- **Resistance Value:** **{formatted}** ({val} Ohms)"

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
            res = {"jsonrpc": "2.0", "id": mid, "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "electronics-mcp", "version": "1.0.0"}}}
        elif m == "tools/list":
            tools = [
                {
                    "name": "component_lookup",
                    "description": "Look up electronic components, ICs, microcontrollers, LCSC/JLCPCB part numbers, and package pinouts.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Component name, e.g. 'ESP32', 'NE555', 'AMS1117-3.3', 'LM358', 'WS2812B'"}
                        },
                        "required": ["query"]
                    }
                },
                {
                    "name": "smd_resistor_calc",
                    "description": "Decode SMD resistor 3-digit, 4-digit, and R-notation marking codes into resistance ohms (e.g. 103 -> 10kΩ, 4R7 -> 4.7Ω).",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "code": {"type": "string", "description": "SMD code, e.g. '103', '4702', '4R7', '0R5'"}
                        },
                        "required": ["code"]
                    }
                }
            ]
            res = {"jsonrpc": "2.0", "id": mid, "result": {"tools": tools}}
        elif m == "tools/call":
            params = req.get("params", {})
            name = params.get("name")
            args = params.get("arguments", {})
            if name == "component_lookup":
                text = lookup_component(args.get("query", ""))
            elif name == "smd_resistor_calc":
                text = decode_smd_resistor(args.get("code", ""))
            else:
                text = f"Unknown tool: {name}"
            res = {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": text}]}}
        else:
            res = {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "Method not found"}}
        sys.stdout.write(json.dumps(res) + "\n")
        sys.stdout.flush()

if __name__ == "__main__":
    main()
