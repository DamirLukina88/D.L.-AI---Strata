---
title: "Workstation Expansion: Miniature Painting, Electronics, and Networking MCP Suites"
type: artifact
description: "Implementation report for minipaint (3,340 paints), electronics (LCSC/JLCPCB/SMD), and networking (SFP/Fiber/PoE) on-demand MCP servers."
status: active
tags: [mcp, electronics, networking, minipaint, hardware, ray]
created: 2026-10-25
updated: 2026-10-25
last_verified: 2026-10-25
---

# Workstation Expansion: Miniature Painting, Electronics, and Networking MCP Suites

## Summary

This update completed the expansion of Ray's on-demand tool catalog, bringing the total number of specialized MCP servers to **30**.

### Newly Implemented Suites
1. **`minipaint` ([`tools/minipaint_mcp.py`](file:///home/damirl/Desktop/Strata/tools/minipaint_mcp.py)):**
   - Packaged local dataset of **3,343 miniature paints** across Citadel, Vallejo, AK 3rd Gen, Army Painter, Scale75, and Monument Pro Acryl.
   - Provides mathematical CIELAB ($\Delta E_{2000}$) paint conversion (`paint_convert`).
   - Airbrush thinning ratios and PSI parameters (`airbrush_guide`).
   - Technical execution guides for Slapchop, Glazing, NMM, and Pin Washing (`technique_guide`).
2. **`electronics` ([`tools/electronics_mcp.py`](file:///home/damirl/Desktop/Strata/tools/electronics_mcp.py)):**
   - Electronic components, microcontrollers (ESP32, RP2040, 555 timers, op-amps, MOSFETs) mapped to **LCSC / JLCPCB SMT part numbers (C-numbers)**, pinouts, and package footprints (`component_lookup`).
   - SMD resistor 3-digit, 4-digit, and R-notation code decoder (`smd_resistor_calc`).
3. **`networking` ([`tools/networking_mcp.py`](file:///home/damirl/Desktop/Strata/tools/networking_mcp.py)):**
   - Optical transceiver form factors (SFP, SFP+, SFP28, QSFP28), wavelengths, and fiber media specs (OM3/OM4 Multi-Mode vs OS2 Single-Mode) (`optics_guide`).
   - RJ45 Ethernet cabling color codes (T568A vs T568B), Cat5e/6/6A bandwidth, and PoE wattage standards (`cabling_pinout`).
   - IEEE OUI MAC address hardware manufacturer lookup (`mac_vendor_lookup`).

---

## Sources

- User requests and conversation: 2026-10-25.
- Central catalog: `~/.config/dl-ai/mcp.json`.
- Tools: `tools/minipaint_mcp.py`, `tools/electronics_mcp.py`, `tools/networking_mcp.py`.
