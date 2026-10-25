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

def calc_pcb_trace(current_a: float, copper_weight_oz: float = 1.0, temp_rise_c: float = 10.0, layer_type: str = "external") -> str:
    """Calculate minimum PCB trace width via IPC-2152 / IPC-2221 standards and provide power decoupling rules."""
    try:
        current = max(0.01, float(current_a))
        oz = max(0.5, float(copper_weight_oz))
        temp_rise = max(1.0, float(temp_rise_c))
        is_ext = layer_type.lower().strip() != "internal"
        
        # IPC-2221 / IPC-2152 empirical formula
        k = 0.048 if is_ext else 0.024
        b = 0.44
        c = 0.725
        area_mils2 = (current / (k * (temp_rise ** b))) ** (1.0 / c)
        thickness_mils = oz * 1.378  # 1 oz copper = ~1.378 mils = ~35 um
        width_mils = area_mils2 / thickness_mils
        width_mm = width_mils * 0.0254
        
        # Resistance and voltage drop estimation per 10 cm (100 mm)
        # Copper resistivity rho = 1.7e-8 ohm-meter
        area_m2 = (width_mm * 1e-3) * (oz * 35e-6)
        r_per_10cm = (1.7e-8 * 0.1) / area_m2
        v_drop = current * r_per_10cm
        power_loss_w = (current ** 2) * r_per_10cm
        
        layer_label = "External (Outer Layer)" if is_ext else "Internal (Inner Layer)"
        
        return (
            f"## IPC-2152 PCB Trace Width & Power Sizing\n\n"
            f"### Parameters:\n"
            f"- **Target Current:** **{current:.2f} A**\n"
            f"- **Copper Weight:** {oz} oz ({oz * 35:.0f} µm)\n"
            f"- **Allowed Temperature Rise:** {temp_rise:.1f} °C\n"
            f"- **Layer Placement:** {layer_label}\n\n"
            f"### Recommended Minimum Trace Width:\n"
            f"- **Width in Millimeters:** **{width_mm:.2f} mm**\n"
            f"- **Width in Mils:** **{width_mils:.1f} mils**\n"
            f"- *Estimated resistance per 100mm:* ~{r_per_10cm * 1000:.2f} mΩ\n"
            f"- *Voltage drop over 100mm:* ~{v_drop * 1000:.2f} mV (Power dissipation: {power_loss_w * 1000:.1f} mW)\n\n"
            f"### High-Speed Digital Power & Decoupling Best Practices:\n"
            f"- **ESP32 & RP2040 Decoupling:**\n"
            f"  • Place a **100 nF (0.1 µF) ceramic X7R** capacitor directly against every VDD pin (< 3 mm distance, short vias to ground plane).\n"
            f"  • Place a **10 µF low-ESR ceramic bulk capacitor** at the 3.3V LDO regulator output.\n"
            f"- **ESP32 RF Peak Current Spikes:**\n"
            f"  • ESP32 Wi-Fi TX bursts pull transient peak currents up to **500 mA**. Size your 3.3V power traces to at least **0.5 mm (20 mils)** to prevent Brownout detector resets.\n"
            f"- **Ground Plane (Return Path):** Keep an uninterrupted solid ground copper pour on Layer 2 directly under high-speed signals (SPI, I2C, UART) to eliminate ground bounce and EMI."
        )
    except Exception as e:
        return f"PCB calculation error: {e}"

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
                },
                {
                    "name": "pcb_trace_and_power_calc",
                    "description": "Calculate minimum PCB trace width (mm and mils) per IPC-2152 standards for current carrying capacity, copper weight (1oz/2oz), and decoupling capacitor rules for ESP32/RP2040.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "current_a": {"type": "number", "description": "Current in amperes (e.g. 1.0, 2.5)"},
                            "copper_weight_oz": {"type": "number", "default": 1.0, "description": "Copper weight in oz (default 1.0 = 35um)"},
                            "temp_rise_c": {"type": "number", "default": 10.0, "description": "Allowed temperature rise in °C (default 10.0)"},
                            "layer_type": {"type": "string", "default": "external", "description": "'external' or 'internal' layer"}
                        },
                        "required": ["current_a"]
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
            elif name == "pcb_trace_and_power_calc":
                text = calc_pcb_trace(args.get("current_a", 1.0), args.get("copper_weight_oz", 1.0), args.get("temp_rise_c", 10.0), args.get("layer_type", "external"))
            else:
                text = f"Unknown tool: {name}"
            res = {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": text}]}}
        else:
            res = {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "Method not found"}}
        sys.stdout.write(json.dumps(res) + "\n")
        sys.stdout.flush()

if __name__ == "__main__":
    main()
