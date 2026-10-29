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

### 7. Resolving PipeWire Audio Hangs & Sentence Truncation (2026-10-24)
- **PipeWire ALSA Plugin Hang Gotcha**: On modern Linux (CachyOS/Arch with PipeWire), ALSA calls route through `pipewire-alsa`. When `piper-speechd` piped output directly into `aplay -q -`, the ALSA emulation layer failed to signal buffer draining at EOF on stdin pipes, causing `aplay` to hang indefinitely. This blocked Speech Dispatcher from sending the completion event, stalled subsequent sentences, and left audio handles frozen.
- **Watchdog Pause/Resume Interruption Gotcha**: `TTSController` ran a periodic 12-second `pause()` and `resume()` heartbeat loop intended as a legacy Chromium 15-second freeze workaround. On Linux and mobile, pulsing `pause()` sent IPC to `TtsPlatformImplLinux`, causing Speech Dispatcher or `aplay` to abort with error `"interrupted"`. `TTSController`'s error handler treated `"interrupted"` as a fatal stop command and cancelled all remaining queued sentences.
- **Premature Chunk Fragmentation**: A low 140-character chunk limit split normal sentences with clauses into fragmented snippets, causing unnatural pauses and resetting prosody. Regex splitting on `[.!?]` also broke after abbreviations (`e.g.`, `i.e.`, `vs.`) and decimal numbers (`23.7 GB`).
- **Solutions**:
  1. Updated `~/.local/bin/piper-speechd` to prioritize PipeWire native `pw-play -` (and fallback `paplay`), guarded against empty/whitespace chunks, and used `printf '%s\n'`.
  2. Replaced the 12s `pause()`/`resume()` heartbeat in `serve/web/app.js` with a 20s stall detector, prevented `"interrupted"` errors from aborting the active queue, and added a 25ms yield on `onend` to allow audio channels to settle cleanly.
  3. Increased natural sentence chunking target to 240 characters and protected common abbreviations, versions, and decimal numbers.

## Verification

- Automated test suite in `tools/test_stt_controller.js` covers 50 test cases (including 5 dedicated TTS filter test cases for emojis, compound emojis, units/currencies, speech symbols, and punctuation stripping).
- All 20 Piper models tested directly in bash with zero aborts or failures.
- Speech Dispatcher service restarted and verified active with `sd_generic`.

## Related

- [Ray: Assistant Name, Voice and Persona](ray-assistant-persona.md): the default voice was HFC female from 2026-10-22, and is HFC male since 2026-10-28.
- [Ray TTS PipeWire Audio Backend and Truncation Fix Report](../artifacts/ray-tts-pipewire-and-truncation-fix-report.md)

## Speed and pitch sliders (2026-10-28)

- **Server voice (web app):** Piper has no pitch setting. Each chunk plays `pitch` times faster through Web Audio (`playbackRate`) and is requested at `speed = rate / pitch`, so the pace stays the Speed setting. A prefetched chunk is fetched again if a slider moved. `--sentence_silence` is scaled by `1/speed` in `serve/speech.py`, which needs a server restart to take effect.
- **Desktop browser voice (speech-dispatcher):** `piper.conf` passes `'$RATE' '$PITCH'` to `~/.local/bin/piper-speechd`, with `GenericRateMultiply 100` / `GenericPitchMultiply 100`. speechd computes `value * Multiply / 100 + Add`, so `1` gave 0. The wrapper turns -100..100 into `3^(v/100)`, Chromium's mapping. Speed goes to `--length_scale` and the pauses. Pitch is an ffmpeg `asetrate` resample, with the phonemes lengthened to keep the pace.
- **Measured** (`en_US-hfc_male-medium`, same sentence): pitch +24 gave f0 119 → 154 Hz (1.29×, asked 1.30); pitch -20 gave 119 → 97 Hz (0.82×, asked 0.80); rate +54 (1.81×) gave 3.87 s → 2.62 s. Phoneme pace in Piper doesn't scale exactly with `length_scale`.
- **Backups** before this change are in the session scratchpad (`piper.conf.bak-rate`, `piper-speechd.bak-rate`).

## Speaking while Ray writes (2026-10-29)

- **The user's request:** speed up Ray's speech by reading the reply sentence by sentence as it is written, instead of after the whole turn. The user chose (with my recommendation) to also speak the short notes before a tool runs, with a guard.
- **How:** `serve/web/speakstream.js` (`SpeakStream`) takes a spoken prompt's reply text as it streams in (`codeEvent` in `serve/web/app.js`) and hands out pieces: a sentence end (`. ! ?` or a blank line) followed by more text, outside an open code block, at least 40 characters (the first may be 24). `TTSController.streamStart/streamSay/streamDrop/streamEnd` queue the pieces on the existing Piper (or browser) voice; while the next sentence is not written yet Ray goes back to thinking after 700 ms (`RayFace.thinking(true)`).
- **Notes:** text that a tool call follows is a note: only its first piece is spoken. At most one note per 15 s; text after a recent note is held until 15 s pass, the turn ends (it was the answer) or another tool call drops it.
- **Switch:** About > *Speak while Ray writes* (`tts_stream`, on). Off is the old path: the last reply read once the turn ends.
- **Measured** (`tools/ray_speech_latency.py`, RX 7600 XT, Qwen3.8-Flash-Next Coder IQ1_M, auto effort, Piper HFC male at pitch 1.5, one run each, a fresh session per prompt):

| Prompt | Tool calls | Turn | First word, after the reply | First word, while written |
| :-- | --: | --: | --: | --: |
| what's the capital of Croatia and what is it known for | 0 | 35.5 s | 36.22 s | 22.82 s |
| how warm is it in Zagreb right now | 2 | 54.1 s | 54.84 s | 51.39 s |
| hey Ray, tell me a fun fact about red pandas | 2 | 31.3 s | 32.21 s | 26.77 s |

- **What that shows:** the gain is the time the answer text takes to write (3.4 to 13.4 s here). Most of the wait before the first word is the model thinking and running tools before it writes anything; in these runs it wrote no note before its tool calls, so none was spoken. Fresh sessions also read the whole prompt cold; in a running conversation both columns are shorter by the same amount. My estimate beforehand (about 10 s down to 1 to 1.5 s) assumed the text starts at once and was wrong.
- **Tests:** `tools/test_speakstream.py` (11 cases, node). Not tested yet: the web app itself in a browser (queue, the face going back to thinking between sentences, Stop mid-stream).

## Filler lines while Ray thinks (2026-10-29)

- **The user's idea:** short summaries of Ray's thinking as gap filler, switching to the answer as soon as it is ready. **Recommended and built instead:** lines made from what is happening, not from the thinking: summarising needs a second model on the GPU that is busy writing the answer (or the cloud), and raw thinking is self-talk that can mention the instructions and contradict the answer. The user agreed ("Built filler lines functionality first").
- **How (`SpeakFiller` in `serve/web/speakstream.js`):** an opener 2 s after a spoken prompt is sent ("Hmm, let me think."), a line per tool as it starts, picked by the tool's name (`FILLER_TOOLS`: "Checking the weather.", "Switching it off." for a Home Assistant `turn_off`, none for `mcp` and housekeeping), and "Still working on it." after 10 s of silence, after the third such line every 30 s. Only while nothing is playing or queued, 8 s after the last line (3 s for a tool's line), never the same line twice running; a tool's line not said within 4 s is dropped. The answer's own text drops filler lines still queued; one already playing (under 2 s) finishes.
- **First version, changed the same day:** "still" lines stopped after three, leaving 93.5 s of silence in a 127 s think, and two of them ("Almost there.", "Nearly got it.") promised an end that was a minute away. Now they continue every 30 s and none promises anything.
- **Switch:** About > *Fill pauses while Ray thinks* (`tts_filler`, on); needs *Speak while Ray writes*. The stream now starts when a spoken prompt is sent, so the opener also covers the prompt reading.
- **Measured** (`tools/ray_speech_latency.py`, recordings of three spoken prompts on the RX 7600 XT, Qwen3.8-Flash-Next Coder IQ1_M, auto effort, a fresh session each, played back through the web app's speech code with Piper measured here: 0.27 s + 0.30 s per 100 characters to make, 4.92 s of speech per 100 characters at pitch 1.5):

| Prompt | Tool calls | Turn | Answer's first word: after the reply / while written / with fillers | Longest silence before it: no fillers / with fillers |
| :-- | --: | --: | --: | --: |
| what's the capital of Croatia and what is it known for | 0 | 141.9 s | 142.3 / 127.3 / 127.3 s | 127.3 / 28.2 s |
| how warm is it in Zagreb right now | 2 | 55.2 s | 55.9 / 51.6 / 51.6 s | 51.6 / 10.3 s |
| hey Ray, tell me a fun fact about red pandas | 1 | 15.4 s | 16.2 / 7.4 / 7.4 s | 7.4 / 2.3 s |

- **What that shows:** fillers do not delay the answer. The Croatia question thought for 127 s this time against 22.8 s an hour earlier (same prompt, auto effort): the thinking before the first word, not speech, is most of the wait on spoken prompts. *(Open: worth looking at the thinking level picked for spoken questions.)*
- **Tests:** `tools/test_speakstream.py`, 19 cases (8 for the filler). Not tested in a browser. The measurement left `speech-latency-…` sessions in the session list.
- **Second version (same day), after the user tried it:** "the fillers sound unnatural". I suggested fewer words, a soft sound for the rest of the wait, and shorter thinking on spoken questions; the user chose the first two. Now: no opener and no "still" lines; at most one spoken line a turn, when a tool starts, in Ray's words ("Let me check the weather.", "Let me switch it off."), only if he has said nothing yet; and a soft sound while he is quiet (`TTSController.chime()`: two sine notes, D5 and F#5, rising and falling in turn, 0.4 s, gain 0.035 at most, low-pass 1.8 kHz, not through the face's analyser), 1.5 s after the prompt, then every 4.5 s, never within 3 s of his voice. The same recordings replayed:

| Prompt | Answer's first word | Longest time before it with no words / with no sound | Line | Sounds |
| :-- | --: | --: | :-- | --: |
| what's the capital of Croatia and what is it known for | 127.3 s | 127.3 / 4.0 s | - | 28 |
| how warm is it in Zagreb right now | 51.7 s | 44.7 / 4.0 s | Let me check the weather. | 11 |
| hey Ray, tell me a fun fact about red pandas | 7.4 s | 3.8 / 1.8 s | Let me check my notes. | 2 |

  Not heard yet: whether the sound itself is pleasant is for the user to judge in the app. Tests: `tools/test_speakstream.py`, 20 cases.

## Preambles instead of fillers (2026-10-29)

- **The user rejected the canned fillers and the soft sound**, and none of 12 Piper samples of "Hmm…", "Let me think…" and similar sounded good to them (Piper has no natural non-verbal sounds). After a look at how other assistants do it (Alexa's progressive responses, OpenAI's realtime "preambles" that describe the action and not the reasoning and avoid "Let me think...", thinking sounds on voice-agent platforms, Google Duplex's disfluencies built into its voice), the user chose the model's own preambles and dropping the fillers and the sound.
- **Now:** `VOICE_NOTE` (`tools/dl_cli.py`, added to spoken prompts only, so the cached start of the prompt is unchanged) asks: "If you use a tool, first write one short sentence saying what you are about to do, the action and not your reasoning." Sentence-by-sentence speech reads that sentence while the tool runs (a note: its first piece, one per 15 s). `SpeakFiller`, `TTSController.chime()` and the *Fill pauses* switch are gone; the stream starts with the reply's first text again, not at sending.
- **Measured** (three new spoken prompts after the daemon restart at 23:35, same setup as above; `tools/ray_speech_latency.py`, recordings replayed through the web app's speech code):

| Prompt | Tool calls | Turn | Answer's first word, after the reply | First word, while written | Answer's first word, while written | Preamble spoken |
| :-- | --: | --: | --: | --: | --: | :-- |
| what's the capital of Croatia and what is it known for | 3 | 94.9 s | 95.3 s | 15.4 s | 82.3 s | I'll check Wikipedia to be accurate about this. |
| how warm is it in Zagreb right now | 2 | 56.1 s | 57.1 s | 23.2 s | 53.1 s | Let me check the live weather for Zagreb. |
| hey Ray, tell me a fun fact about red pandas | 2 | 31.7 s | 32.6 s | 27.3 s | 27.3 s | - |

- **Two bugs found by that run, fixed:** (1) a preamble right before a tool call was never spoken: a sentence counted as finished only once more text followed, and a tool call followed instead; `tool()` now lets the note out. (2) Only the turn's first piece could be short (24 characters), so "The capital of Croatia is Zagreb." after a tool waited 2 s to be joined; now the first piece after each tool call may be short too. The table is with both fixes.
- **Bug found by the user the same evening ("he is now reading the thinking block and stopping"):** with thinking off (small talk), the preamble sentence made the model answer "What can you do?" with only "The user is asking about my capabilities, so I should just answer directly without calling any tools." or "No tools needed, I'll just answer that one directly." (2 of 2 turns), and stop. Turns that thought first used the preamble well. Fix: `voice_note(thinking)` in `tools/dl_cli.py` adds `VOICE_PREAMBLE` only when the turn's thinking level is not none (`dl_sessiond.Session._agent` passes it); `test_preamble_only_when_the_model_thinks` in `tools/test_dl_sessiond.py`. Daemon restarted.
- **Seen, one run each:** the model wrote a preamble in 2 of 3 turns with tools (none for the red panda fact). The Croatia question used Wikipedia this time (0 tools in the two runs before the note changed), perhaps nudged by the note's mention of tools *(inferred, one run)*. Its first spoken word came at 15.4 s instead of 82.3 s; the long silence after the preamble is the model thinking.

## Sources

- User, chat, 2026-10-28: pitch and speed controls did not work for the voice

1. User, chat, 2026-10-17.
2. Chromium Linux Speech Dispatcher backend: `content/browser/speech/tts_linux.cc`.
3. Speech Dispatcher module specification: `piper.conf` & `sd_generic`.
4. Piper TTS issue tracker & C++ source: `piper/src/cpp/phonemize.cpp`.
5. Local Whisper STT Integration: [local-whisper-speech-to-text.md](local-whisper-speech-to-text.md).
