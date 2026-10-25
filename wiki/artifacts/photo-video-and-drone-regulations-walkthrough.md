---
title: "Workstation Expansion: Photo, Video, and Drone Regulations MCP Suites"
type: artifact
description: "Report for photovideo (exposure, log profiles, storyboarding) and drones (DJI specs, Croatian CCAA/EASA rules, AMC Portal) MCP servers."
status: active
tags: [mcp, photography, videography, drones, croatia, ccaa, amc-portal, ray]
created: 2026-10-25
updated: 2026-10-25
last_verified: 2026-10-25
---

# Workstation Expansion: Photo, Video, and Drone Regulations MCP Suites

## Summary

This update completes the creation and registration of two specialized on-demand MCP servers for media production and aerial operations, bringing the total number of specialized MCP servers in Ray's catalog to **34**.

### Newly Implemented Suites
1. **`photovideo` ([`tools/photovideo_mcp.py`](file:///home/damirl/Desktop/Strata/tools/photovideo_mcp.py)):**
   - **Exposure & 180° Shutter Rule (`exposure_calc`):** Computes EV100, evaluates motion blur via the 180-degree cinematic shutter rule ($1 / (2 \times \text{fps})$), and recommends Neutral Density (ND) filter strength (ND16 to ND64) when shooting at native base ISO outdoors.
   - **Log Profiles (`log_profile_guide`):** Technical breakdown of Sony S-Log3, Canon C-Log3, DJI D-Log / D-Log M, and Panasonic V-Log, specifying dual native ISOs, gamma curve behavior, middle-grey/white IRE targets, and monitoring LUTs.
   - **Storyboarding & Shot Framing (`storyboard_shot_guide`):** Cinematography reference for ELS, LS, MS, MCU, CU, ECU, Over-The-Shoulder (OTS), and Dutch Angle framing, along with 180-degree axis guidelines.

2. **`drones` ([`tools/drones_mcp.py`](file:///home/damirl/Desktop/Strata/tools/drones_mcp.py)):**
   - **DJI Drone Specifications (`dji_drone_specs`):** Technical hardware specs for DJI Mini 4 Pro, Mini 3 Pro, Air 3, and Mavic 3 Pro (takeoff weights, EASA C0/C1/C2 class marks, O3/O4 transmission ranges, wind resistance, and camera systems).
   - **Croatian & EASA Drone Regulations (`croatia_drone_rules`):** Comprehensive guide on mandatory CCAA operator registration (applicable to all drones with optical sensors), Open A1/A2/A3 competency certificates, 120m AGL maximum ceiling, and automated flight approvals via Croatia Control's AMC Portal (AMC Portal Mobile app for Zagreb LDZA CTR up to 50m AGL).

---

## Sources

- User requests: 2026-10-25.
- Central catalog: `~/.config/dl-ai/mcp.json`.
- Tools: `tools/photovideo_mcp.py`, `tools/drones_mcp.py`.
- Regulations: Croatian Civil Aviation Agency (CCAA / HACZ), Croatia Control (HKZP AMC Portal), EASA Easy Access Rules for UAS.
