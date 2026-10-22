---
title: "Ray: Assistant Name, Female Voice and Persona"
type: decision
description: "D.L. AI is now Ray; Piper HFC female voice; casual persona crediting Damir's stack on every Chat request"
status: active
tags: [ray, persona, tts, stt, branding, speech-dispatcher]
created: 2026-10-22
updated: 2026-10-22
last_verified: 2026-10-22
---

# Ray: Assistant Name, Female Voice and Persona

## Summary

On 2026-10-22 the user renamed the assistant from D.L. AI to **Ray**: female voice, professional-butler manner, used
hands-free (STT → model → TTS).

## Choices (the user's answers)

- **Name**: changed everywhere a person sees or hears it: web app title, header, empty chat, monitor page, lock-screen
  media title ("Ray Response", "Ray · Strata"), the Settings voice test line, the D.L. CLI identity prompts
  ("You are Ray, …"), scheduled-job and approval notifications ("Ray: job #…"), watchdog log lines, the sessiond unit
  `Description=`, `dl_agent_bench.py` help text.
- **Kept on purpose**: the program name "D.L. CLI" (its `[D.L. CLI]` notes are matched by `startswith` in
  `tools/dl_cli.py` and its tests), file names (`dl_cli.py`, `dl_sessiond.py`), `~/.config/dl-ai/`, the
  `dl-ai-sessiond.service` unit name, docstrings, and the `// D.L. AI:` fork-change markers in code comments.
- **Voice**: Piper `en_US-hfc_female-medium`.
  - Web: `TTSController.getVoice()` in `serve/web/app.js` prefers `hfc_female` when no voice is saved; the Auto option
    reads "Auto (Ray: Piper HFC female)". A voice already saved in a browser still wins.
  - Desktop: Speech Dispatcher picks by voice *type*, and its default type is MALE1 (Ryan). Now
    `DefaultVoiceType "FEMALE1"` in `~/.config/speech-dispatcher/speechd.conf`, and in `modules/piper.conf` the `en`
    FEMALE1 slot and the `en-US` FEMALE1 slot were swapped (hfc_female ↔ lessac-medium) so all 20 voices stay listed.
    `DefaultVoice` there is also hfc_female. Backups: `*.bak-20261022-ray`.
  - `~/.local/bin/piper-speechd` still falls back to lessac: that is the crash-safe fallback, not Ray's voice.
- **Persona, revised the same day** (`RAY_IDENTITY` and `RAY_VOICE` in `serve/web/app.js`): the model kept saying it was
  made by Alibaba / Qwen, so Ray now carries who built what.
  - Tone: casual and direct, friendly person rather than butler; light humour; mild swearing only if the user swears
    first; never "sir", "madam" or the user's name.
  - Credit, given in full whenever identity comes up: Damir built Ray. She runs on Damir's PC (RX 7600 XT, ROCm,
    CachyOS) on Damir's customised fork of the open-source Strata engine, server and web app; the model is
    Qwen3.8-Flash-Next, weights released by Alibaba's Qwen team, which did not build or run her. She also knows D.L. CLI
    and the Code tab, the offline Whisper + Piper voice pipeline, and the Home Assistant setup (lights, Gree AC, Bambu A1,
    Xiaomi cameras, Tuya, via MCP).
  - `RAY_IDENTITY` is the system message of **every** Chat tab request (typed chats now send one too); a spoken (STT)
    prompt adds `RAY_VOICE` (one to three spoken sentences, no markdown).
  - The D.L. CLI identity prompts (act and plan mode) carry the same credit line; their coding manner is unchanged.

## Verification

- Browser pane, 2026-10-22 (after the revision): a typed prompt's request starts with one system message holding the
  identity; a simulated spoken one has the identity plus the voice rules. Title, header and empty chat read "Ray". No live answer was checked (the local server needs the API key).
- `node tools/test_stt_controller.js` 53/53; `tools/test_dl_{schedule,sessiond,agent_bench,context,memory,mcp}.py` OK.
- `app.js` cache tag bumped to `v=20261022-ray2` in `serve/web/index.html`.

## Related

- [Desktop Piper Voice Switching and STT-Only Auto-Speak Gating](desktop-piper-voice-switching-and-stt-auto-speak.md)

## Sources

1. User, chat, 2026-10-22.
