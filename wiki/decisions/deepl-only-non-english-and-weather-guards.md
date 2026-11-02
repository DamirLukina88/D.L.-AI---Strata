---
title: "DeepL-Only Non-English Mail Guard and Geocoded Hourly Weather"
type: decision
description: "Non-English email guard via DeepL language detection, geocoded hourly weather tool, tomorrow in Now prefix, and reviewer send visibility."
status: active
tags: [deepl, email, guard, weather, mcp, reviewer, croatian]
created: 2026-11-01
updated: 2026-11-01
last_verified: 2026-11-01
---

# DeepL-Only Non-English Mail Guard and Geocoded Hourly Weather

## Summary

Following an incident where Ray authored a Zagreb weather email in English while believing it was Croatian, four fixes were implemented to enforce translation integrity and eliminate coordinate/date errors.

## Problem & Diagnosis

On 2026-11-01 (session `dl-ai-code`):
1. **Language Illusion**: Ray attempted to write Croatian directly, but emitted English phrases (`"Weather in Zagreb"`, `"Highest temperature"`, `"Hour by hour"`) believing they were Croatian. The system prompt rule began with `- Translating:`, which the model didn't trigger since it was authoring the page rather than answering an explicit translation prompt.
2. **Coordinates From Memory**: Ray queried Open-Meteo with Venice coordinates (45.53, 12.22) from memory instead of Zagreb (45.815, 15.982), reporting a sunny 17.5 °C while Zagreb was raining at 8.2 °C.
3. **Weekday Miscalculation**: Ray called Monday 2.11.2026 "Saturday".
4. **Reviewer False Alarm**: The finish check reviewer claimed no email was sent because `request_actions` truncated at 3,000 characters before reaching the `proton__send_mail` action.

## Decisions & Implementation

1. **Non-English Mail Guard & Prompt Rule**:
   - In `tools/dl_cli.py`, the prompt rule now mandates English by default and strictly prohibits writing or editing Croatian, German, or other non-English text without DeepL.
   - In `tools/dl_translate.py`, `check_email_language` uses DeepL to detect the outgoing body's language. English passes; non-English passes only if its content or file hash matches a recorded `deepl__translate` output from the current session.
   - Enforced in `tools/dl_proton.py` (`send_mail`) and `tools/dl_mcp.py` (`send_mail`, `send_gmail_message`).
2. **Geocoded Hourly Weather MCP Tool**:
   - `tools/weather_mcp.py` (`get_weather`) now supports `hourly: bool` and `day: str` (`today`, `tomorrow`, or `YYYY-MM-DD`). It geocodes the city automatically via OpenStreetMap Nominatim and builds a 24-hour table with condition, temperature, rain chance/mm, wind speed and compass direction, and daylight times.
   - Added prompt instruction: *"Never type coordinates or IDs from memory; use a tool that looks them up."*
3. **Tomorrow in Time Prefix**:
   - `now_line()` in `tools/dl_cli.py` now includes tomorrow's date: `[Now: nedjelja, 01.11.2026. 21:18 (Europe/Zagreb) — sutra: ponedjeljak, 02.11.2026.]`.
4. **Reviewer Send Visibility**:
   - In `request_actions`, file editing arguments are shortened to 80 characters, and external communication actions (`send_mail`, `send_gmail`, `deepl`, `schedule`, `draft_mail`) are prioritized and placed at the top so the 3,000-character cap never drops them.

## Verification

- `tools/test_dl_translate.py`: 11 tests pass (English allowed, recorded DeepL allowed, untranslated Croatian blocked, DeepL unreachable error handled).
- `tools/test_dl_proton.py`: 32 tests pass.
- `tools/test_weather_mcp.py`: 3 tests pass (compass direction, coordinates, hourly table formatting).
- `tools/test_dl_review_actions.py`: 2 tests pass (`now_line` with `— sutra:`, `request_actions` external action prioritization).
- `tools/test_dl_sessiond.py`, `test_dl_context.py`, `test_dl_memory.py`: all pass without regressions.

## Related

- [Ray: Assistant Name, Voice and Persona](ray-assistant-persona.md)

## Sources

1. User, chat, 2026-11-01.
