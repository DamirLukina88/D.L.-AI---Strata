---
title: "Native Browser TTS Implementation Report"
type: artifact
description: "Implementation, architectural mitigations, and cross-platform verification for native browser Text-to-Speech in Strata App Chat and Code Chat."
status: active
tags: [web, tts, speech, android, brave, chrome]
created: 2026-10-17
updated: 2026-10-17
last_verified: 2026-10-17
---

# Native Browser TTS Implementation Report

## 1. Overview & Objectives

This report documents the implementation and verification of client-side Native Browser Text-to-Speech (TTS) across the D.L. AI / Strata web interface, covering both **App Chat** (`#view-chat`) and **Code Chat** (`#view-code`).

The solution operates with zero external network requests, zero server CPU/GPU overhead, and complete user privacy.

### Supported Platforms & Browsers
- **Desktop Google Chrome / Chromium**: Full Web Speech API with V8 GC retention and 10s watchdog heartbeat.
- **Desktop Brave Browser**: Local system voice prioritization, gesture-compliant audio unlocking, and privacy-shield auto-play fallback.
- **Android Google Chrome**: Web Speech API bridge to Android system TextToSpeech service, Screen Wake Lock API, and sentence-boundary chunking (&le;180 chars).
- **Android Brave Browser**: Brave mobile shields compatibility, background tab sleep mitigation, and touch-unlocked playback pipeline.
- **Native Android System Audio Integration**: `navigator.mediaSession` integration with Android notification shade and lock-screen playback controls (Play, Pause, Stop), paired with a microscopic silent WebAudio keep-alive buffer.

---

## 2. Architecture & Implementation

### 2.1 Core TTS Controller (`TTSController`)
Located in `serve/web/app.js`:
- **State Management**: Tracks playback states (`idle`, `playing`, `paused`, `activeBtn`, `activeMsg`).
- **Watchdog Timer**: Chromium engines suffer from a known 15-second speech stall bug where synthesis freezes silently without emitting `onend` or `onerror`. `TTSController` runs a 10-second `pause()` and `resume()` heartbeat loop while active, refreshing Chromium's internal watchdog timer.
- **V8 GC Anchor**: In Chromium V8, `SpeechSynthesisUtterance` instances are prematurely garbage collected if not retained in global scope. `TTSController.currentUtterance` retains the active object until completion.
- **Screen Wake Lock**: Automatically requests `navigator.wakeLock.request('screen')` during playback to prevent mobile devices from sleeping mid-sentence, releasing cleanly on finish or stop.
- **Android MediaSession**: Publishes `MediaMetadata` ("D.L. AI Response", "D.L. AI · Strata") to the Android notification drawer and lock screen, binding native media actions (`play`, `pause`, `stop`).
- **Silent WebAudio Buffer**: Plays a microscopic silent loop via `AudioContext` during active synthesis, preventing Android's power manager and audio HAL from dropping audio focus between sentence chunks.

### 2.2 Text Preprocessing & Sanitization (`cleanForSpeech`)
- **Reasoning Filtering**: Strips `<think>...</think>` tags and unclosed thinking streams completely.
- **Code Block Handling**: Configurable in Settings:
  - `skip` (Default): Replaces code blocks with `"[Code block omitted.]"`.
  - `summary`: Replaces code blocks with language and line counts (e.g. `"[python code block, 12 lines.]"`).
- **Markdown Stripping**: Cleanly strips headings (`#`), bold/italics (`**`, `*`), blockquotes (`>`), bullets (`-`, `*`), numbered lists (`1.`), inline code (`` ` ``), and converts markdown links to display text.
- **Math / LaTeX**: Strips formula markers (`$$`, `$`).

### 2.3 Sentence Boundary Chunker (`chunkText`)
- Automatically segments long assistant responses into natural sentences (&le;180 characters) using regex lookaheads on punctuation (`. `, `? `, `! `, `; `, `\n`).
- Handles long clauses with comma/dash splitting and words fallback to guarantee zero buffer drops on mobile Android TTS engines.

---

## 3. UI/UX Integration

1. **App Chat (`#view-chat`)**:
   - Each assistant message bubble includes a native speaker button `[data-msg-speak]` alongside `[data-msg-copy]`.
   - Clicking the button plays that message; clicking again stops it.
   - While playing, the button glows with the Strata accent color (`--st-accent`) and switches to an `i-volume-x` icon.
2. **Code Chat Mobile Card View (`#code-mobile-messages`)**:
   - Each assistant reply and output card features an action bar containing copy and read-aloud buttons.
   - Includes quick `/speak` chip in the mobile composer and slash command support.
3. **Code Chat Desktop Terminal View**:
   - A dedicated `#code-speak-btn` speaker button is integrated into the top terminal action bar (`.code-terminal-actions`).
4. **Settings & Configuration UI**:
   - A dedicated **Voice & Speech (TTS)** card inside the **About** view:
     - Voice selection dropdown (enumerates available system voices with offline indicators).
     - Speed slider (0.7x to 1.8x, default 1.0x).
     - Pitch slider (0.8 to 1.3, default 1.0).
     - Code block reading mode selector (`skip`, `summary`, `verbatim`).
     - Auto-read toggle (disabled by default).
     - "Test voice" button.

---

## 4. Verification & Testing

### 4.1 Automated Unit Tests (`tools/test_tts_sanitizer.js`)
All 6 automated unit tests passed with 100% assertions:
- `Test 1`: `<think>` tags completely eliminated.
- `Test 2`: Code block 'skip' mode replacement.
- `Test 3`: Code block 'summary' mode with line count calculation.
- `Test 4`: Markdown formatting syntax stripped.
- `Test 5`: Long text (482 chars) cleanly chunked into 4 chunks (all &le;180 chars).
- `Test 6`: Unpunctuated run-on clause cleanly word-split.

### 4.2 Syntax & Asset Delivery Verification
- `node --check serve/web/app.js`: Clean exit (0 errors).
- `python3 -c "import xml.etree.ElementTree as ET; ET.parse('serve/web/sprite.svg')"`: Clean XML syntax.
- Live HTTP curl to `http://127.0.0.1:8080/`: Verified delivery of `index.html`, `app.js?v=20261017-tts`, and `sprite.svg?v=20261017-tts`.
- Secret scan audit via `tools/dl_auditing.py`: 100% clean, 0 secret violations across all 5 modified files.

---

## 5. Artifacts & Commits

- **Local Backup**: `/mnt/data/Strata-data/local_backups/tts_native_browser_20261017_131854/`
- **Unit Test Suite**: `tools/test_tts_sanitizer.js`
- **Git Commit**: `d04bbc8a` (`feat(web): implement native browser TTS in App Chat and Code Chat with Android and Brave optimizations`)

---

## Sources

- [W3C Web Speech API Specification](https://wicg.github.io/speech-api/) — Official Web Speech API standard specification.
- [W3C Media Session Standard](https://w3c.github.io/mediasession/) — Standard for platform media notifications and lock screen integration.
- [W3C Screen Wake Lock API](https://w3c.github.io/screen-wake-lock/) — Screen wake lock interface specification.
- [Chromium Issue 679437 / 339023](https://issues.chromium.org/issues/40502120) — Chromium speech synthesis 15-second pause/freeze bug and watchdog workaround.

