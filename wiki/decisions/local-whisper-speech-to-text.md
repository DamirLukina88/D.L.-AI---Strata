---
title: "Local Whisper Speech-to-Text (STT) Integration"
type: decision
description: "Implements 100% offline, local Whisper STT via whisper.cpp and MediaRecorder for Desktop Brave and all browsers"
status: active
tags: [stt, whisper, whisper-cpp, brave-browser, audio, media-recorder]
created: 2026-10-17
updated: 2026-10-17
last_verified: 2026-10-17
---

# Local Whisper Speech-to-Text (STT) Integration

## Summary

Resolves speech dictation restrictions in Desktop Brave and other browsers by embedding 100% local, offline Whisper speech recognition (`whisper-cpp` + `ggml-base.bin`) into Strata. Audio recorded via standard HTML5 `MediaRecorder` is transcribed on the host PC in ~200ms with zero data leakage to cloud servers.

## Context & Problem
Brave Browser on Desktop disables Google's cloud SpeechRecognition API by default for privacy, preventing dictation and triggering `service-not-allowed` / `network` errors when users attempt Web Speech API voice typing. Furthermore, users running local LLMs (such as Strata Qwen3.8 Coder on PC) expect complete voice privacy with zero audio streaming to third-party cloud servers.

## Decision
1. **Local Whisper Engine (`whisper-cpp` & `ggml-base.bin`):**
   - Installed native `cachyos-extra-v3/whisper-cpp` (`/usr/bin/whisper-cli`) and `ffmpeg`.
   - Placed official multi-lingual `ggml-base.bin` (141 MB) at `~/.local/share/whisper/models/ggml-base.bin`.
   - Runs in ~200ms per utterance with 100% local CPU/GPU acceleration and zero idle memory footprint (process exits immediately after transcribing).

2. **OpenAI-Compatible Backend Endpoint:**
   - Implemented `POST /v1/audio/transcriptions` and `GET /v1/audio/status` in `serve/server.py` backed by `serve/transcribe.py`.
   - Supports standard multipart `FormData` (`file`, `language`, `prompt`), JSON base64, and raw audio streams.
   - Converts browser audio (WebM Opus, OGG, WAV, etc.) to 16kHz mono 16-bit PCM WAV on the fly via `ffmpeg`.
   - Protects the endpoint with standard Strata API key / Cloudflare Access bearer authorization.

3. **Frontend Hybrid STT Controller (`serve/web/app.js` & `index.html`):**
   - `STTController` supports both local recording via HTML5 `MediaRecorder` + `AudioContext` VAD (Voice Activity Detection), and browser-native `SpeechRecognition`.
   - Automatic fallback: If browser speech throws `service-not-allowed` or `network` (e.g. in Brave Browser), Strata automatically switches to local Whisper without interrupting the user.
   - Added user engine selection in Settings drawer:
     - `Automatic` (prefers local Whisper when installed)
     - `Local Whisper` (100% offline, works in all browsers including Brave Desktop)
     - `Browser Native Speech` (Web Speech API)
   - Integrated hands-free auto-send buttons on both Chat (`#auto-send-btn`) and CLI Coding (`#code-mobile-auto-send-btn`), maintaining synced state across views.
   - Implemented turn-level voice input gating (`code.turnFromVoice`) so that "Automatically read new answers aloud" triggers at turn completion (`turn_end`) in CLI Coding mode exclusively when the prompt was spoken via STT, preserving silence for keyboard-entered requests.

4. **Hands-Free Walking, Instant Auto-Send & Toast Non-Blocking:**
   - **Live Progressive Transcription During Speech:** As the user walks and speaks, partial audio slices are transcribed in the background on conversational pauses (>1.0s) or speech milestones (>2.5s), visibly populating the composer textarea in real time.
   - **Instant Auto-Send (0ms Delay):** When Auto-Send is on, the recognized text is populated into the composer input field (`#input` or `#code-mobile-input`) and submitted immediately without artificial delays.
   - **Non-Blocking Instant Toast Dismissal:** Notification toasts (`.st-toasts`) have `pointer-events: none !important;` with individual toasts set to `pointer-events: auto; cursor: pointer;`. A global `pointerdown` capture listener instantly clears active toasts on any screen tap or toast click, and forwards clicks to any underlying interactive elements (buttons, toggles) without swallowing user input or blocking the UI.

## Gotchas & Pitfalls
- **Mobile Virtual Keyboard Pop-up During Voice Dictation:** Calling `ta.focus()` after speech transcription or leaving the input focused when tapping the microphone button on smartphones caused Android/iOS to constantly pop up the virtual software keyboard, obscuring the screen. Solved by:
  1. Calling `document.activeElement.blur()`, `ta.blur()`, and `navigator.virtualKeyboard.hide()` immediately on mic pointerdown and click.
  2. Setting `inputmode="none"` on the target textarea while voice recording / transcribing.
  3. Removing unconditional `ta.focus()` calls from transcription completion callbacks.
  4. Restoring `inputmode` dynamically when the user intentionally taps or clicks into the textarea to type.
- **Drawer `aria-hidden` vs Focused Descendant:** In Chromium browsers, applying `aria-hidden="true"` to `<aside id="drawer">` when `#s-apply` holds focus throws `Blocked aria-hidden on an element because its descendant retained focus`. Solved by blurring any active child inside the drawer before closing, restoring focus to the opening trigger button (`#sampling-btn` / `#code-sampling-btn`), and applying the HTML5 `inert` attribute to the closed drawer.
- **Toast Obstructing Underlying Elements:** Popup notifications (such as "Auto-send enabled") previously sat over interactive controls for 3.5 seconds with pointer events enabled, preventing immediate interactions. Solved with capture-phase `pointerdown` dismissal and `document.elementsFromPoint` click forwarding.
- **DOM Teardown Race in Auto-Send:** Calling `updateInput()` inside `cleanup()` after transcribing caused textarea values to be blanked before `send()` or `codeSend()` could read them, causing early submission aborts. Fixed by decoupling `cleanup()` from DOM mutation and passing `overrideText` directly to `send(text)` and `codeSend(text)`.
- **Transcribing Click Flood:** Multiple rapid taps on the mic button while `isTranscribing` was active could spawn duplicate audio recorder instances. Guarded by ignoring toggle clicks while `isTranscribing` is `true`.

## Verification
- `tools/test_stt_transcribe.py` passed (6/6 tests covering status detection, log/timestamp stripping, synthetic WAV/WebM transcription).
- `tools/test_stt_controller.js` passed (53/53 tests covering transcript merging, dual-mode hold/tap interaction, auto-send gating, dual auto-send button sync, CLI coding voice-only auto-speak, instant auto-send, drawer accessibility focus restoration, toast non-blocking instant dismissal, and mobile virtual keyboard suppression).

## Sources
- `serve/transcribe.py`: local Whisper CLI and ffmpeg transcoder integration.
- `serve/server.py`: backend `v1/audio/transcriptions` and `v1/audio/status` endpoints.
- `serve/web/app.js`: `STTController` with `MediaRecorder`, VAD silence auto-stop, progressive interim updates, and visual confirmation countdown.
- `serve/web/index.html`: `autosend-bar`, `code-autosend-bar`, and review delay setting dropdown.
- `serve/web/app.css`: hardware-accelerated animated countdown banner styles.
- `tools/test_stt_transcribe.py`: Backend transcription verification suite.
- `tools/test_stt_controller.js`: Frontend STT transcript, countdown, and engine controller tests.
