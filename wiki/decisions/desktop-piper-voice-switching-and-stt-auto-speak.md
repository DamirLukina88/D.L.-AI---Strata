---
title: "Desktop Piper Voice Switching and STT-Only Auto-Speak Gating"
type: decision
description: "Resolves Speech Dispatcher generic module quoting for Piper TTS, Chromium Linux voice keys, and gates auto-speak to STT voice prompts only"
status: active
tags: [tts, stt, speech-dispatcher, piper, web-speech-api, audio]
created: 2026-10-17
updated: 2026-10-17
last_verified: 2026-10-17
---

# Desktop Piper Voice Switching and STT-Only Auto-Speak Gating

## Summary

This decision documents two critical speech subsystem fixes: (1) resolving Speech Dispatcher argument quotation and Chromium Linux voice key mapping so that all 20 local Piper neural voices switch reliably on Desktop, and (2) gating the "Automatically read new answers aloud" feature to only trigger when the user prompt was submitted via Speech-to-Text (STT voice typing), preserving silent typing workflows.

## Context & Key Gotchas

### 1. Speech Dispatcher `sd_generic` Parameter Passing
- **Gotcha**: In `~/.config/speech-dispatcher/modules/piper.conf`, the `GenericExecuteSynth` directive substitutes `$VOICE`. If escaped with literal octal or hex quotation artifacts (such as `\x27$VOICE\x27`), Speech Dispatcher's generic module does not unescape hex characters. Instead, it passes literal `x27<voice>x27` as `$1` to the execution wrapper.
- **Consequence**: The wrapper `piper-speechd` looked for `en_US-bryce-medium.onnx` prefixed by literal `x27` characters (`x27en_US-bryce-mediumx27.onnx`). Failing the existence check, it silently fell back to `en_US-lessac-medium.onnx` on every invocation, giving the illusion that voices were not switching.
- **Solution**:
  1. Normalized single quotes in `piper.conf`.
  2. Added defensive sanitization in `~/.local/bin/piper-speechd`:
     ```bash
     RAW_VOICE="${1:-en_US-lessac-medium}"
     VOICE_NAME=$(echo "$RAW_VOICE" | sed "s/^[\\'\"]*//; s/[\\'\"]*$//; s/^x27//; s/x27$//")
     VOICE_NAME="${VOICE_NAME:-en_US-lessac-medium}"
     ```

### 2. Chromium Linux Voice Key Mapping
- **Gotcha**: In Chromium's Linux implementation (`TtsPlatformImplLinux`), voices registered from Speech Dispatcher are stored in a map where the key is `<spd_voice_name> <module_name>` (e.g. `en_US-bryce-medium piper`). In the Web Speech API, `SpeechSynthesisVoice.voiceURI` and `SpeechSynthesisVoice.name` can vary between browser engines.
- **Solution**: In `serve/web/app.js`, `TTSController.getVoice()` matches both `v.voiceURI === uri || v.name === uri`. Furthermore, `tts-test-btn` actively syncs `#tts-voice-select.value` to local storage immediately before triggering synthesis, ensuring instant feedback when sampling voices.

### 3. Conversational Auto-Speak Gating (STT Only)
- **Constraint**: Users who type prompts on a keyboard expect silent text interaction. Auto-speak read-aloud is designed for hands-free voice conversational loops (STT &rarr; LLM &rarr; TTS).
- **Implementation**:
  - `STTController` tracks `lastInputWasVoice` and `lastTranscribedText` upon transcribing speech chunks.
  - In `send()` and `codeSend()`, `fromVoice` is computed by verifying that the submitted prompt contains or matches `lastTranscribedText`.
  - Input listeners on `#input` and `#code-mobile-input` reset `lastInputWasVoice` if the field is completely cleared by the user.
  - In `endStreaming()` and `codeEnd()`, playback only starts if `TTSController.isAutoSpeak() && m.fromVoice`.
  - Manual message speaker buttons remain clickable on any message regardless of prompt origin.

## Verification

- Automated test suite in `tools/test_stt_controller.js` covers 20 test cases, verifying:
  - Disjoint, cumulative, and overlapping STT transcript merging.
  - Pure typed prompt auto-speak rejection (`fromVoice === false`).
  - STT voice prompt auto-speak acceptance (`fromVoice === true`).
  - Multi-turn turn state resets and prompt replacement detection.
  - Cross-browser voice URI / name lookup matching.
- Piper models verified directly against `speechd` SSIP client.

## Sources

1. User, chat, 2026-10-17.
2. Chromium Linux Speech Dispatcher backend: `content/browser/speech/tts_linux.cc`.
3. Speech Dispatcher module specification: `piper.conf` & `sd_generic`.
