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

### 4. Piper 1.2 Multi-Codepoint Phoneme Crash & Hardened Fallback
- **Gotcha**: Piper C++ engine 1.2.0 strictly requires that every entry in `phoneme_id_map` is a single UTF-8 codepoint. The voice model `en_US-mike-medium.onnx.json` contained multi-character diphthongs (`aɪ`, `aʊ`, `ɔɪ`, `eɪ`, `oʊ`), causing Piper to throw `std::runtime_error: Phonemes must be one codepoint` and dump core (`SIGABRT`).
- **Consequence**: When `piper` dumped core, Speech Dispatcher's `sd_generic` module terminated. Speech Dispatcher does not auto-restart dead generic modules, leaving the desktop TTS pipeline completely unresponsive until systemd restart.
- **Solution**:
  1. Sanitized `en_US-mike-medium.onnx.json` to filter out multi-character phonemes (verified Mike speaks cleanly without core dump).
  2. Hardened `~/.local/bin/piper-speechd` to buffer stdin, catch any synthesizer failure, fall back to `en_US-lessac-medium.onnx`, and guarantee `exit 0`, preventing `sd_generic` from ever crashing.

### 5. Rapid Voice Sampling Test Button Fix
- **Gotcha**: In `serve/web/app.js`, `TTSController.speakText` treated re-clicking the active button during playback as a toggle-off command (`wasSame`), which was intended for chat message bubbles. When rapidly switching voices in settings and clicking "Test voice", the second click cancelled playback and returned immediately without playing the new voice.
- **Solution**: Exempted `tts-test-btn` from `wasSame` toggling; it now stops previous playback and immediately starts testing the newly selected voice.

### 6. TTS Emoji & Symbol Filtering
- **Gotcha**: When reading responses aloud, the browser speech synthesis / Speech Dispatcher literally pronounced emoji names (e.g. reading 😄 as "open face smiley" or "smiling face with open mouth") and announced technical/formatting punctuation ("open parenthesis", "pipe", "asterisk", "tilde").
- **Unicode Keycap Gotcha**: Unicode property escape `\p{Emoji_Component}` matches ASCII digits `0-9` because digits are components of keycap sequences (`1️⃣`). Using `\p{Emoji_Component}` inadvertently stripped all numbers.
- **Solution**: Enhanced `cleanForSpeech()` in `serve/web/app.js`:
  1. Strips emojis using `[\p{Extended_Pictographic}\p{Emoji_Modifier}\uFE0E\uFE0F\u200D]+` (excluding `Emoji_Component` so digits are preserved).
  2. Strips technical punctuation (`~`, `|`, `^`, `#`, `*`, `_`, `\`, `/`, box drawing, decorative bullets, arrows).
  3. Translates speech-friendly symbols into words (`%` $\rightarrow$ "percent", `&` $\rightarrow$ "and", `+` $\rightarrow$ "plus", `$` $\rightarrow$ "dollars", `°C` $\rightarrow$ "degrees Celsius").
  4. Converts parentheses to gentle commas so speech intones naturally without vocalizing "parenthesis".

## Verification

- Automated test suite in `tools/test_stt_controller.js` covers 50 test cases (including 5 dedicated TTS filter test cases for emojis, compound emojis, units/currencies, speech symbols, and punctuation stripping).
- All 20 Piper models tested directly in bash with zero aborts or failures.
- Speech Dispatcher service restarted and verified active with `sd_generic`.

## Related

- [Ray: Assistant Name, Female Voice and Persona](ray-assistant-persona.md): the default voice is now HFC female.

## Sources

1. User, chat, 2026-10-17.
2. Chromium Linux Speech Dispatcher backend: `content/browser/speech/tts_linux.cc`.
3. Speech Dispatcher module specification: `piper.conf` & `sd_generic`.
4. Piper TTS issue tracker & C++ source: `piper/src/cpp/phonemize.cpp`.
5. Local Whisper STT Integration: [local-whisper-speech-to-text.md](local-whisper-speech-to-text.md).
