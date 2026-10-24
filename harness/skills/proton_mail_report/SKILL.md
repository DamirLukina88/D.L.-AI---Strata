# Skill: Weather & Daily Digest Proton Mail Report

Use this skill when preparing and sending daily digests or weather reports via Proton Mail.

## Prerequisites
- Tool: `dl_proton.py` or MCP mail tool.
- Network access for live weather data.

## Procedure
1. **Location Inference & Data Fetch**:
   - Determine target location from user prompt or default settings.
   - Fetch verified weather forecasts using `run_command` with curl wttr.in or python script.

2. **Compose Clean Plaintext / HTML Report**:
   - Format: Clean summary table of temperature, precipitation, and conditions.
   - Do not include raw terminal ANSI escapes or broken formatting.

3. **Approval Gate & Send**:
   - Display draft summary for user confirmation unless running under autonomous scheduled job.
   - Dispatch via `python tools/dl_proton.py send --subject "..." --body "..."`.
