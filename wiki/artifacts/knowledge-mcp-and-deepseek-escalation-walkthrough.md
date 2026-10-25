---
title: "Knowledge MCP Suites and DeepSeek Hybrid Escalation Walkthrough"
type: artifact
description: "Implementation walkthrough for DeepSeek cloud reasoning, on-demand MCP knowledge suites, and Open-Meteo live weather integration."
status: active
tags: [mcp, deepseek, knowledge, weather, tools, dl-cli, ray]
created: 2026-10-25
updated: 2026-10-25
last_verified: 2026-10-25
---

# Knowledge MCP Suites and DeepSeek Hybrid Escalation Walkthrough

## Summary

This session integrated a comprehensive set of on-demand knowledge MCP servers into Ray's central catalog (`~/.config/dl-ai/mcp.json`) and added gated DeepSeek cloud reasoning while enforcing a privacy-first architecture.

### Key Milestones
1. **Privacy-Preserving DeepSeek Cloud Escalation:**
   - Deployed [`tools/deepseek_mcp.py`](file:///home/damirl/Desktop/Strata/tools/deepseek_mcp.py) (`deepseek_reason`).
   - Default: strictly local inference on AMD RX 7600 XT. DeepSeek is dormant unless explicitly approved by the user or enabled via `/mcp on deepseek`.
   - Credential securely stored in `wiki/private/.env` (`DEEPSEEK_API_KEY`).
2. **28 On-Demand MCP Servers Configured:**
   - **Academic & Science:** `arxiv` (AI/ML/CS preprints), `openalex` (250M+ scholarly works graph), `europepmc` (life sciences full text), `pubchem` (chemical & molecular formulas).
   - **Biomedical & Clinical:** `clinicaltrials` (ClinicalTrials.gov studies), `opentargets` (therapeutic targets), `reactome` (biological signaling cascades).
   - **Engineering & Standards:** `print3d` (Klipper G-code & Bambu/Prusa filament presets), `cadmaterials` (STEP AP242/IGES/B-Rep & AFLOW alloys), `rfc` (IETF internet standards), `devstandards` (Game Programming Patterns & MDN), `modernweb` (Modern Web Guidance), `osv` (package vulnerability audit).
   - **Reference, Geography & Law:** `wikipedia` (REST summaries), `osm` (OpenStreetMap coordinates), `laws` (Narodne Novine/Zakon.hr & EUR-Lex/CURIA), `weather` (Open-Meteo instant weather for Zagreb & global).
3. **CLI Ergonomics & Help Sync:**
   - Synchronized `/help` in [`tools/dl_sessiond.py`](file:///home/damirl/Desktop/Strata/tools/dl_sessiond.py) and [`tools/dl_cli.py`](file:///home/damirl/Desktop/Strata/tools/dl_cli.py).
   - Automated routing regex triggers verified with 100% test pass rate across all domain categories.

---

## Sources

- User conversation and deployment commands: 2026-10-25.
- Central catalog: `~/.config/dl-ai/mcp.json`.
- Tools: `tools/deepseek_mcp.py`, `tools/weather_mcp.py`, `tools/print3d_mcp.py`, `tools/cad_materials_mcp.py`, `tools/dev_standards_mcp.py`, `tools/laws_eu_hr_mcp.py`.
