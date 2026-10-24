---
title: "Ray TTS PipeWire Audio Backend and Truncation Fix Report"
type: artifact
description: "Resolves PipeWire aplay hangs, 12s pause watchdog interruptions, and natural sentence chunking for Ray Text-to-Speech in Strata Code Chat."
status: active
tags: [tts, speech, piper, pipewire, chromium, audio]
created: 2026-10-24
updated: 2026-10-24
last_verified: 2026-10-24
---

# Ray TTS PipeWire Audio Backend and Truncation Fix Report

## 1. Overview & Problem Description

When users listened to Ray's voice replies in the Strata Code interface (via hands-free STT auto-speak or manual message read-aloud buttons), speech playback frequently cut off mid-sentence or truncated entire answers.

### Observed Symptoms
1. **Mid-Sentence Interruption at ~12 Seconds**: Answers taking longer than 12 seconds stopped abruptly mid-word or mid-sentence, dropping the remainder of the assistant's reply.
2. **Missing Sentences & Choppy Delivery**: Sentences containing numbers, abbreviations, or multiple clauses were fragmented across rapid utterances with unnatural pauses, and occasionally skipped trailing clauses entirely.
3. **`synthesis-failed` Socket Desync**: Browser consoles logged `SpeechSynthesisErrorEvent {error: 'synthesis-failed'}` when the system Speech Dispatcher service reloaded without a corresponding browser socket restart.

---

## 2. Root Cause Analysis

### 2.1 PipeWire ALSA Emulation Hang on Standard Input
In `~/.local/bin/piper-speechd`, synthesized audio from Piper was piped into `aplay -q -`.
On modern Linux systems using PipeWire (`pipewire`, `wireplumber`, and `pipewire-pulse`), ALSA applications route through the `pipewire-alsa` plugin. When streaming raw PCM audio bytes over standard input (`stdin`), `aplay` failed to receive the EOF drain callback from the ALSA emulation plugin, causing the `aplay` process to hang indefinitely holding the audio stream open.

Because `aplay` hung:
- `piper-speechd` never exited with return code 0.
- Speech Dispatcher's `sd_generic` output module was blocked waiting on the child process.
- No `onend` completion event was emitted to Chromium.
- Subsequent utterances in the speech queue were stalled or failed with `synthesis-failed`.

### 2.2 Periodic 12-Second Heartbeat Watchdog Interruption
To combat a legacy 15-second utterance stall bug in Chromium on Windows/macOS, `TTSController.startWatchdog()` in `serve/web/app.js` executed an interval every 12 seconds:
```javascript
this.watchdogTimer = setInterval(() => {
  if (window.speechSynthesis && window.speechSynthesis.speaking && !window.speechSynthesis.paused) {
    window.speechSynthesis.pause();
    window.speechSynthesis.resume();
  }
}, 12000);
```
On Linux using Speech Dispatcher (`TtsPlatformImplLinux`), invoking `window.speechSynthesis.pause()` sent an immediate pause/stop IPC request to `sd_generic`. This abruptly halted playback and caused Chromium to fire a `SpeechSynthesisErrorEvent` with `error: "interrupted"`.

In `app.js`, the error handler treated `"interrupted"` as a fatal stop command:
```javascript
if (this.currentIndex < this.queue.length && e.error !== "canceled" && e.error !== "interrupted") {
  this.speakNext();
} else {
  this.stop(); // Wiped the entire remaining queue
}
```
Any speech playback lasting longer than 12 seconds was actively killed by the heartbeat timer.

### 2.3 Aggressive 140-Character Chunking & Punctuation Splitting
- The chunk threshold in `TTSController.chunk` was set to 140 characters. Normal sentences of 20–25 words were aggressively chopped at commas into disconnected clauses, spawning a separate Piper ONNX synthesis subprocess and ALSA stream for each clause.
- Sentence boundary splitting regex `/(?<=[.!?;\n])\s+/` broke after decimal numbers (`23.7 GB`) and common abbreviations (`e.g.`, `i.e.`, `vs.`, `dr.`).
- HTML tag stripping (`/<[^>]+>/g`) indiscriminately stripped text between mathematical inequalities (`<` and `>`), omitting content in code or logic explanations.
- Synchronously queueing `speakNext()` inside `u.onend` triggered race conditions in Chromium while the previous utterance's audio channel was still settling.

---

## 3. Implementation & Architecture Fixes

### 3.1 Native PipeWire Audio Wrapper (`~/.local/bin/piper-speechd`)
Updated `piper-speechd` to prioritize native PipeWire streaming over ALSA emulation:
```bash
# Pick best audio player for system: PipeWire native pw-play > PulseAudio paplay > ALSA aplay
if command -v pw-play >/dev/null 2>&1; then
    PLAY_CMD="pw-play -"
elif command -v paplay >/dev/null 2>&1; then
    PLAY_CMD="paplay"
else
    PLAY_CMD="aplay -q -"
fi

# Do not invoke synthesis if text is empty or only whitespace
if [ -z "$(echo "$DATA" | tr -d '[:space:]')" ]; then
    exit 0
fi

# Synthesize audio with requested model; if it fails, safely retry with fallback
if ! printf '%s\n' "$DATA" | "$HOME/.local/bin/piper" --model "$MODEL" --output-file - 2>/dev/null | $PLAY_CMD; then
    if [ "$MODEL" != "$FALLBACK" ]; then
        printf '%s\n' "$DATA" | "$HOME/.local/bin/piper" --model "$FALLBACK" --output-file - 2>/dev/null | $PLAY_CMD || true
    fi
fi
```
In `~/.config/speech-dispatcher/modules/piper.conf`, updated `GenericCmdDependency "pw-play"`.

### 3.2 Hang-Only Watchdog & Resilient Error Recovery (`serve/web/app.js`)
1. **Removed Heartbeat Pause/Resume**: Eliminated the periodic 12s pulsing loop. Replaced it with a 20-second chunk stall watchdog that only intervenes if an active chunk makes zero progress:
   ```javascript
   let lastIndex = this.currentIndex;
   let stuckCount = 0;
   this.watchdogTimer = setInterval(() => {
     if (!this.speaking || window.speechSynthesis?.paused) return;
     if (this.currentIndex === lastIndex) {
       stuckCount++;
       if (stuckCount >= 4) { // 4 ticks of 5s = 20s stuck on same chunk
         console.warn("TTS watchdog: chunk stalled for 20s, advancing to next chunk");
         stuckCount = 0;
         this.currentIndex++;
         this.speakNext();
       }
     } else {
       lastIndex = this.currentIndex;
       stuckCount = 0;
     }
   }, 5000);
   ```
2. **Resilient Error Recovery**: Unexpected `"interrupted"` or `"canceled"` events no longer wipe out the queue when `this.speaking` is true. Playback yields 35ms and advances to the next chunk.
3. **Channel Settle Yield**: Added a 25ms yield in `u.onend` before triggering `speakNext()`, allowing the browser audio device to cleanly close before dispatching the next utterance.

### 3.3 Natural 240-Character Chunking & Abbreviation Protection
Updated `chunkText` in `serve/web/app.js` with a 240-character target, preserving complete sentences and natural prosody:
- Protected abbreviations (`e.g.`, `i.e.`, `vs.`, `dr.`, `mr.`, `ms.`) and decimal numbers (`\d+\.\d+`) by temporarily shielding dots with unicode `\u2024`.
- Updated HTML tag stripping in `cleanForSpeech` to `/<[a-zA-Z\/][^>]*>/g`, ensuring math inequalities (`count < 10 and max > 50`) remain intact.

---

## 4. Verification & Validation

### 4.1 Audio Backend Performance Comparison
Benchmarked on CachyOS Linux (PipeWire 1.2, WirePlumber 0.5):
- `aplay -q -` on stdin WAV stream: **Timed out / Hung** after 3.0s.
- `pw-play -` on stdin WAV stream: **Completed in 1.42s** (returncode 0).
- `paplay` on stdin WAV stream: **Completed in 1.47s** (returncode 0).
- Consecutive multi-sentence benchmark (3 sentences): **1.66s, 1.79s, 1.66s**, all returncode 0 with zero zombie or hanging processes.

### 4.2 Test Suite Execution
- `node tools/test_tts_sanitizer.js`: **10/10 unit tests passed** (including decimal protection and inequality retention).
- `node tools/test_stt_controller.js`: **53/53 tests passed**.
- Core Python test suite (`test_dl_tool_calls.py`, `test_dl_effort.py`, `test_dl_session_tools.py`): **60/60 tests passed**.
- Pre-commit secret audit (`tools/pre-commit-scan-secrets.py --all`): **Clean, 0 secrets**.
- Browser Cache Buster: Updated in `serve/web/index.html` to `?v=20261024-ttsfix`.

---

## 5. Related Decisions

- [Desktop Piper Voice Switching and STT-Only Auto-Speak Gating](../decisions/desktop-piper-voice-switching-and-stt-auto-speak.md)
- [Ray: Assistant Name, Female Voice and Persona](../decisions/ray-assistant-persona.md)
- [Native Browser TTS Implementation Report](native-browser-tts-implementation-report.md)

## Sources

- User request & live browser console trace, 2026-10-24.
- Chromium Linux Speech Dispatcher backend: `content/browser/speech/tts_linux.cc`.
- PipeWire Native Multimedia Playback: `pw-play(1)` & `pipewire-alsa`.
