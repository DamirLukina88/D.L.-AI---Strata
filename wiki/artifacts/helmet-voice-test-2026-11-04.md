---
title: "Helmet Voice Test (2026-11-04)"
type: artifact
description: "Ray through the D.L. SENA helmet, timed on the PC mic, phone and server: why he didn't hear, the fix, baseline vs re-check numbers"
status: active
tags: [android, companion, helmet, bluetooth, validation]
created: 2026-11-04
updated: 2026-11-04
last_verified: 2026-11-04
---

# Helmet Voice Test (2026-11-04)

## Summary

The user reported five problems calling Ray with the D.L. SENA helmet (Shark, Sena firmware 1.0.2) on the Xiaomi 17
Ultra: a strange different voice answers, sometimes nothing opens, it misses words, no answer in the helmet, music stays
off. `tools/helmet_test.py` recorded the Blue Snowball on the PC and lined it up, by clock, with the phone's live log
(USB), the audio HAL's log, the server journal and the shared session's events.

The helmet sends voice recognition when its main button is held until two beeps (`startVoiceRecognitionByHeadset`, then
`VOICE_COMMAND` to Ray's trampoline). Root causes found:

| Problem | Cause | Fix (commit `50df006f`) |
| --- | --- | --- |
| Misses words / doesn't hear | The call link (virtual call) came up in 0.5 s, 6 s or never; Android dropped it ~6.5 s into each listen (`updateActiveForUid 10069 false`: a link is kept only for an app that plays or records, and Google's recognizer records, not Ray); the phone mic took over when the link was late | Listening uses `BluetoothHeadset.startVoiceRecognition` / `stopVoiceRecognition` |
| The press that did nothing | Voice recognition was never ended toward the helmet, so its next hold sent "stop" (`stopVoiceRecognitionByHeadset ... not started`) | `stopVoiceRecognition` when listening ends |
| Strange voice, no answer in the helmet (away from home) | Ray's voice used its own network client, always the LAN address: 15 s timeout, then the phone's voice at pitch 1.5 on the music stream, which the helmet doesn't play while the call link is open | Shared route; voice fetched while the link comes up; one retry |
| Music stays off | The phone-voice fallback never reported done: call link, audio focus and "speaking" stayed held | `UtteranceProgressListener` and a time limit |

Gotcha that cost most of the session: with the helmet on the desk and the user talking at its mic from outside, the
helmet's noise gate sends exact digital zeros between words (and for the first 3-4 s), and its level peaks around
-50 dB. That made every link look broken. Test with the helmet worn.

## Numbers

| Run | Setup | Heard right | Answer in Ray's voice | Notes |
| --- | --- | --- | --- | --- |
| Baseline, old build | helmet on the desk | 0 of 4 (1 partial: "is it today") | 1 of 4 | link 0.5 s / 6 s / never; dropped at ~6.5 s |
| Mic test 1-2 (`MicProbeActivity`) | helmet on the desk | zeros, then -48..-56 dB bursts | — | the same with either link and either audio mode |
| Mic test 3 | helmet worn | "One ... ten", complete | — | voice-recognition link ready 0.72 s; call link 1.92 s (lost "one") |
| Re-check, this build | helmet worn | 4 of 4 | 4 of 4 (Piper, LAN and tunnel) | link up 0.44-0.60 s, recognizer ready 0.77-0.94 s after the press |

Re-check detail: route probe picked the tunnel in 0.13-0.16 s (LAN probe failed in ~0.07 s, in parallel); Piper took
0.5-2.2 s on the server; on the tunnel a 704-character answer (1.8 MB WAV) reached the phone in 4.5 s. No phone-voice
fallback, no link drop, no "stop" press. The model's time dominated (5.4-62 s). The user noticed the helmet's call
channel closing while Ray thought and opening again for his answer (listening and the answer use separate links).

## Round 2: music and repeats (same build, helmet worn)

8 steps, 9 presses (`..._203137`). Music came back after Ray's answer every time (3 of 3 music steps, and the song left
playing through the next steps): fixed. Heard right: 5 of 9 presses on the first listen (one more on the retry);
garbled 3 (recognizer heard loud input, level 10, but "No speech recognized" or "today is today"); silent 1 (level -2 for
10 s, like the desk tests). One press opened the drawer and the system hid it 0.5 s later, while it listened: the phone
was dozing (AOD), the drawer turned the screen on, `MiuiDozeService` stopped, then `RayVoiceSession onHide` — the old
"sometimes nothing opens". Audio routing was the same in good and bad presses (Brave paused by the recognizer's focus at
~0.8 s; its earcons play over the helmet link); Bluetooth quality reports show only "A2DP choppy" at each switch to the
helmet link, in good and bad presses alike. What the recognizer received in the bad listens is not recorded yet.

## Round 3: music vs no music, dozing phone (adds the reopen of a drawer the system hides)

7 presses (`..._205504`). No drawer was hidden this time (the reopen is untested). Music came back every time. Heard:
locked with music 0 of 2 (both silent: level -2 for 10 s), then a second press "what time is"; locked without music 2
of 2; unlocked "image a short joke" (music) and "today is it today" (no music): the helmet's noise gate clips the first
word, and Ray still answered both.

Over rounds 2 and 3: **phone locked with music playing failed 5 of 6** (silent or garbled); locked without music 4 of 4
(and 2 of 2 in the re-check). In a silent press the phone suspended the music link (A2DP PLAYING -> NOT_PLAYING) and
opened the mic link 10 ms later; with no music it opened the mic link at once. Inferred: the helmet doesn't switch from
music to mic that fast on a locked phone; the phone side looks the same in good and bad presses.

Ray can't keep a copy of what the recognizer hears: while Google's recognizer listens, Android silences any other
recording (RecordActivityMonitor: Ray "silenced", the recognizer "not silenced"), so a copy needs Ray to do the listening
himself.

## Round 4: pause the song first (commit after `2636fe68`)

The locked-with-music case only (`..._210957`): with music playing to the helmet at a press, Ray takes the audio focus
(the song pauses), waits for the music link to stop (1.5 s at most) plus 0.4 s, then starts voice recognition. Heard
4 of 4 (1 of 6 before); one partial ("joke"). The phone never reported the music link stopped within 1.5 s, so each
press waited ~1.9 s and the mic link still opened over a live A2DP stream: the helmet only needed the song silent
first. Cost: Ray listens 2.8-3.2 s after the press instead of ~0.9 s (only when music plays); words said before the
helmet's link-open beep are lost. A shorter pause (~0.8 s) was not tried: the user chose to keep this one (2026-11-04).

## Not tested yet

Riding (wind, pocket); the reopen of a drawer the system hides.

## Related

- [Ray Hybrid WebView Companion and Phone MCP Architecture](../decisions/ray-hybrid-webview-companion-and-phone-mcp.md)
- [Ray Companion Validation (2026-11-02)](ray-companion-validation-2026-11-02.md)

## Sources

1. `~/.local/share/dl-ai/helmet-tests/2026-11-04_190512` (baseline), `..._193805-probe`, `..._195123-probe`,
   `..._200034-probe`, `..._201509` (re-check): Snowball audio, phone log, HAL log, server journal, traces.
2. Sena app (com.sena.shark) Device Settings, viewed over adb 2026-11-04: no mic sensitivity setting; HD Voice on,
   VOX off, Audio Source Priority Intercom.
3. User, chat, 2026-11-04: symptoms, the two-beep hold, test notes.
4. Opus runs, 2026-11-04 23:44-23:51: the app's `voice_trace.jsonl`, the `strata-server` journal, `dumpsys media.player`,
   driven over adb with a temporary test build (not committed).
