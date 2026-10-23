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
  - Without Piper (a phone, Edge, macOS) "Auto" used to take the first Natural/Neural voice, often male (Edge lists
    "Microsoft Andrew Online (Natural)" early). Since 2026-10-23 every fallback step takes a female voice of its kind
    first (`RAY_FEMALE_VOICE` in `serve/web/app.js`: Ava, Jenny, Aria, Google US English, Samantha, Android `-x-sfg`
    and more). Checked in the browser pane with fake voice lists: Edge → Ava, Chrome → Google US English, Android →
    `en-us-x-sfg-local`, desktop Piper → hfc_female.
  - Android Chrome (92 voices on the user's phone) names voices by language only ("English United States", lang
    `en_US` with an underscore, `[local]`), so no female name matched and Auto took the first English voice, which
    was male. The user fixed it by hand by picking "English United States (en_US) [local]". Now, with no female name,
    each step prefers a local `en-US`/`en_US` voice, then any `en-US` one (checked with an Android-style list in the
    browser pane).
  - A voice saved in a browser still wins over Auto, and "Test voice" saves the selected one: sampling a male voice
    keeps it. Pick "Auto" in Settings to go back.
- **Auto-read on by default** (2026-10-23): "Automatically read new answers aloud" (`tts_auto_speak`) is on unless
  turned off. It reads only answers to spoken (STT) prompts; a saved "off" is kept.
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

- **Thinking off for spoken prompts** (2026-10-22): Settings > Speech > "Skip thinking for voice prompts"
  (`#tts-fast-voice-toggle`, `TTSController.isFastVoice()`, browser key `voice_no_thinking`, **on by default**, per
  browser). When on, a spoken (STT) prompt is sent with thinking off; typed prompts are unchanged.
  - Chat tab: `send()` sets `reasoning_effort: "none"`.
  - Code tab: `codeSend()` adds `effort: "none"` to the `input` op; `serve/server.py` passes `effort` through to
    `tools/dl_sessiond.py`, where `submit(..., effort=)` runs that one turn at it. The session's `/effort` level is left
    as it was. Test: `TurnEffort` in `tools/test_dl_sessiond.py`.
  - Checked in the browser pane with requests intercepted: spoken Chat → none, typed Chat → the Thinking setting, spoken
    Code → none, typed Code → no effort (session level); with the toggle off, spoken prompts send no override.

- **Gotcha: the model took the owner's name for the speaker's** (2026-10-23). The coding agent greeted everyone as
  Damir ("Hello Damir — I'm Ray") because its prompt said "The user: <name>, <email>" (from
  `~/.config/dl-ai/profile.json`) and "Damir, the developer, built you". Fix: the profile line no longer names
  anyone (the email stays for "send me"); `RAY_ABOUT` in `tools/dl_cli.py` says the speaker is unknown unless they give
  a name, names Damir only for credit, treats "you", small talk and STT spellings (Rey, Rae, Wray, Re) as addressed to
  Ray and answered without tools, and says not to talk about the rule (one run recited it: "Whoever's using this
  machine"). Chat's `RAY_IDENTITY` has the same rules. Benchmark and the prompt trim: [Ray Persona Bench](../artifacts/ray-persona-bench-2026-10-23.md).

- **The Chat tab was removed** (2026-10-23, the user: "the basic chat is no longer needed"). The Code tab is the start
  tab; `#chat` and the old `/?q=` shortcut now just open Code. Removed: the Chat view and its code in
  `serve/web/app.js` (send, render, attachments, `RAY_IDENTITY`/`RAY_VOICE`, its saved history is no longer read), its
  styles in `serve/web/app.css`, and the Chat-only drawer rows ("Show thinking", "Use tools from MCP servers").
  `components.css` (the design system) was left as it is. Speech-to-text now targets the Code prompt only. The
  workspace dialog's "Attach" adds an `@/absolute/path` reference to the Code prompt (D.L. CLI reads @file references;
  a path with spaces is refused with a toast).
  - Ray's household persona moved into the coding agent's `RAY_ABOUT` in `tools/dl_cli.py` (female, casual, light
    jokes, mild swearing only if the user swears, no sir/madam; credit adds the voice pipeline and the Home Assistant
    setup), so the terminal CLI has it too.
  - The spoken-answer rules are `VOICE_NOTE` in `tools/dl_cli.py`, added after the text of a spoken prompt only: the
    web app sends `voice: true` with the `input` op, `serve/server.py` passes it through, and `tools/dl_sessiond.py`
    appends the note to that user message. The system prompt stays the same, so the cached prefix is kept. Test:
    `test_a_spoken_turn_gets_the_voice_note` in `tools/test_dl_sessiond.py`.
  - The server-side MCP servers on the Monitor (`serve/mcp.py`) stay for API clients that ask for them.

## Verification

- Browser pane, 2026-10-22 (after the revision): a typed prompt's request starts with one system message holding the
  identity; a simulated spoken one has the identity plus the voice rules. Title, header and empty chat read "Ray". No live answer was checked (the local server needs the API key).
- `node tools/test_stt_controller.js` 53/53; `tools/test_dl_{schedule,sessiond,agent_bench,context,memory,mcp}.py` OK.
- `app.js` cache tag bumped to `v=20261023-ray5` in `serve/web/index.html`.

## Related

- [Ray Persona Bench and Prompt Trim (2026-10-23)](../artifacts/ray-persona-bench-2026-10-23.md)
- [Desktop Piper Voice Switching and STT-Only Auto-Speak Gating](desktop-piper-voice-switching-and-stt-auto-speak.md)

## Sources

1. User, chat, 2026-10-22.
