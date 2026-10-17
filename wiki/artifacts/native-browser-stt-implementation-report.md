---
title: "Native Browser STT Implementation Report"
type: artifact
description: "Implementation, push-to-talk, Brave privacy bypass, and verification for native browser Speech-to-Text in App Chat and Code Chat."
status: active
tags: [web, stt, speech, dictation, brave, chrome, android]
created: 2026-10-17
updated: 2026-10-17
last_verified: 2026-10-17
---

# Native Browser STT Implementation Report

## 1. Overview & Objectives

This report documents the implementation and verification of client-side Native Browser Speech-to-Text (STT / Voice Typing) across the D.L. AI / Strata web interface, covering both **App Chat** (`#view-chat`) and **Code Chat** (`#view-code`).

The solution operates entirely client-side using standard Web Speech APIs (`SpeechRecognition` / `webkitSpeechRecognition`), requiring zero server GPU or Python backend changes, preserving complete user privacy and enabling hands-free or quick voice prompt input.

### Supported Platforms & Browsers
- **Desktop Google Chrome / Chromium**: Full continuous speech recognition with real-time interim streaming.
- **Desktop Brave Browser**: Automatic detection of Brave privacy blocks with guided modal (`#brave-stt-dialog`) explaining on-device flags and keyboard/system dictation options.
- **Android Google Chrome**: Native Android speech recognition engine bridge with real-time streaming into mobile input elements.
- **Android Brave Browser**: Touch-friendly push-to-talk interaction, zero latency speech capture, and keyboard dictation (Gboard) compatibility.

---

## 2. Architecture & Implementation

### 2.1 Core STT Controller (`STTController`)
Located in `serve/web/app.js`:
- **State Management**: Tracks recording state (`isRecording`), interaction mode (`isPushToTalk`), target view (`currentTarget`), accumulated final text (`finalText`), and active interim hypothesis (`interimText`).
- **Real-time Live Streaming**: Listens to recognition `onresult` events, splitting final sentences and interim hypotheses, cleanly appending them to any preexisting text inside `#input` or `#code-mobile-input`.
- **Dynamic Textarea Autosizing**: Automatically triggers `autosize()` for App Chat and dynamic `scrollHeight` bounds (up to 160px) for Mobile Code input as speech is recognized in real time.
- **4-Second Silence Auto-Stop**: Continuously resets a 4000ms silence timer during active speech; automatically ends recording if user stops speaking.
- **TTS Interruption**: Automatically interrupts and stops active speech synthesis (`TTSController.stop()`) when dictation starts to prevent model voice self-feedback.

### 2.2 Dual-Mode Interaction Engine (`bindDualMode`)
Supports two interaction paradigms transparently across mouse and touch inputs:
1. **Tap-to-Toggle Mode**: Quick click or tap (<400ms) toggles recording ON or OFF.
2. **Push-to-Talk (Hold-to-Talk) Mode**: Press and hold (>400ms) activates recording while held; releasing stops recording immediately.
- Clean event suppression guarantees that releasing a hold does not fire a subsequent toggle click.

### 2.3 Mirrored Auto-Send Functionality
- **Hands-Free Dictation**: When Auto-Send is enabled, finishing dictation (via silence timeout, push-to-talk release, or stop click) automatically submits the prompt (`send()` for App Chat, `codeSend()` for Code Chat).
- **Dual-Control Synchronization**: Accessible via a quick toggle in the composer bar (`#auto-send-btn`) and synchronized bidirectionally with the setting toggle in **About &rarr; Voice & Dictation** (`#stt-auto-toggle`).
- Persisted locally across browser sessions in `localStorage` under `strata.stt_auto_send`.

### 2.4 Multi-Language Support
- **Language Selector (`#stt-lang-select`)**: Supports English (US, UK), German, French, Spanish, Italian, Croatian, Serbian, Bosnian, Mandarin, Japanese, and Russian.
- Defaults intelligently to `navigator.language` or `en-US` and persists user preference in `localStorage` under `strata.stt_lang`.

### 2.5 Brave Browser Compatibility Guidance
- Brave Browser blocks Google Speech Recognition API endpoints by default for privacy, returning `service-not-allowed` or `network`.
- **Detection & Modal**: Detects Brave via `navigator.brave.isBrave()` or Brave user agents and automatically opens the `#brave-stt-dialog` modal.
- Explains why cloud speech endpoints are restricted, recommends on-device options (Gboard mic on mobile, OS dictation or Chrome on desktop), and enables copying flag configurations.
- Also permanently accessible via the "Setup Guide" button in Settings.

### 2.6 Visual Indicator & GUI Assets
- **SVG Symbols (`serve/web/sprite.svg`)**:
  - `<symbol id="i-mic">`: Microphone outline with subtle translucent fill.
  - `<symbol id="i-mic-off">`: Strikethrough microphone for active recording state.
  - `<symbol id="i-auto-send">`: Lightning bolt icon for auto-send hands-free mode.
- **Recording Pulse (`serve/web/app.css`)**:
  - Active mic buttons receive `.is-recording` class featuring high-visibility red glow animation (`@keyframes st-mic-pulse`).

---

## 3. Test Suite & Verification

### 3.1 Unit Testing (`tools/test_stt_controller.js`)
All 9 automated unit tests passed (100%):
- **Transcript Merging**:
  - Test 1: Empty base text with interim speech &rarr; trimmed speech.
  - Test 2: Existing base text without trailing space &rarr; cleanly spaced concatenation.
  - Test 3: Existing base text with trailing newline &rarr; newline preservation.
  - Test 4: Merging base text, final accumulated transcript, and active interim speech.
- **Dual-Mode Interaction Simulation**:
  - Test 5: Short tap (150ms) triggers click toggle without hold.
  - Test 6: Long press (600ms) triggers push-to-talk start and stop on release, suppressing click.
- **Auto-Send Conditions**:
  - Test 7: Auto-send enabled with spoken words triggers submission.
  - Test 8: Auto-send enabled with empty speech / aborted session suppresses submission.
  - Test 9: Auto-send disabled retains text in composer without submitting.

### 3.2 Regression & Secret Audit
- `node --check serve/web/app.js`: Syntax check passed (Exit code 0).
- `node tools/test_tts_sanitizer.js`: Existing TTS tests intact (6/6 passed).
- `python3 tools/pre-commit-scan-secrets.py`: Clean scan across all modified files (zero leaks).
- `curl -s http://127.0.0.1:8080/`: Live HTTP verification confirmed all assets served with fresh cache-busting headers (`?v=20261017-stt`).

---

## Sources

- W3C Web Speech API Specification: `SpeechRecognition` interface.
- Chromium Issue 1152286: SpeechRecognition behavior and network endpoints.
- Brave Community Documentation: Enabling Google Speech Services in `brave://settings/system`.
- User chat session, 2026-10-17.
