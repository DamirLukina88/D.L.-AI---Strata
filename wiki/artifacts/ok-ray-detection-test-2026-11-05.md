---
title: "Ok Ray Detection Test (2026-11-05)"
type: artifact
description: "Old vs quick-fix wake word on 20 Piper voices and the Xiaomi 17 Ultra: false alarm rates, CPU, why Vosk confidence is useless in grammar mode"
status: active
tags: [android, companion, wake-word, validation]
created: 2026-11-05
updated: 2026-11-05
last_verified: 2026-11-05
---

# Ok Ray Detection Test (2026-11-05)

## Summary

The user reported too many false positives from "Ok Ray" and wanted lower power. The quick fix keeps Vosk and changes
three things in `HotwordListenerService` / `WakeWord`: only final results count (partial results fired before), the
grammar holds 33 look-alike phrases besides the wake phrases, and a loudness gate (`SpeechGate`) keeps Vosk from running
on a quiet room. A custom small model (microWakeWord) remains the planned real fix; see Follow-up.

## Numbers

Test audio: 20 local Piper en_US voices, each clip with light (-60 dB) and heavier (-35 dB) white noise, run through the
same `vosk-model-small-en-us-0.15` on the PC with Python vosk. Synthetic voices and noise, not real rooms or the user's voice.

| Logic | Real phrase wakes | First look-alike list wakes (1,680) | Held-out look-alikes wake (1,200) |
| --- | --- | --- | --- |
| Old: partial or final, 2 phrases + `[unk]` | 160 of 160 | 1,221 (72.7%) | not run |
| Final results only, same grammar | 159 of 160 | 741 (44.1%) | 392 (32.7%) |
| Final only, 10-phrase grammar | 153 of 160 | 359 (21.4%) | 227 (18.9%) |
| **Shipped: final only, 35 phrases + `[unk]`** | **140 of 160 (87.5%)** | **64 (3.8%)** | **75 (6.3%)** |

The shipped grammar's decoys were picked with the first list in view, so the held-out column is the fair one. Worst
held-out phrases: "hockey Ray" 23 of 40, "okay lay" 21, "oh Ray" 11, "okay Roy" 10. "oh gray" from the first list: 29 of 40.

Ordinary English speech as one stream (1.7 h, 1,200 sentences from the docs): old 4 wakes; final only 0; shipped 0.

Phone, Xiaomi 17 Ultra (SM8850), debug build, app in the background, on battery, on a desk in a quiet room (-61 dB), 60-70 s,
`/proc` thread times:

| | Listener thread | Whole app |
| --- | --- | --- |
| Ok Ray off | none | 0.4% of one core |
| Old listener | 6.22% | 6.9% |
| Quick fix | 0.91% | 1.5% |

Vosk ran 10% of that minute. In constant speech the gate stayed open 96% of the time on the PC, so with a TV or a
conversation in the room the saving mostly goes away. Not measured on the phone: mAh, loud rooms, Croatian speech, pocket.

Live, PC speakers to the phone: four look-alike clips did not wake him; the first "okay ray" opened the drawer (0.72 s
phrase), and listening came back 0.6 s after the drawer closed.

## Gotchas

- **Vosk's word confidence is useless in grammar mode.** Real phrases and look-alikes both score about 0.5 (158 of 159
  real and 687 of 742 false hits were 0.5 or more; nothing reached 0.6). A first version required 0.90 and would have
  refused every real phrase. Don't add a confidence threshold back.
- A second pass with the open vocabulary separates them but says "okay ray" for only 59% of real clips ("okay right",
  "okay way", ...), so it was dropped for the decoys.
- A result must be exactly the phrase, so the user has to pause after "Ok Ray"; "Ok Ray what's the time" won't wake him.
- The old listener never closed its `Recognizer`; the new loop closes it.
- Editing `shared_prefs` with `run-as` while the app runs doesn't stop the service: force-stop first.

## Follow-up

Replace Vosk with a custom small model trained on "Ok Ray" (microWakeWord first, openWakeWord as fallback; Porcupine ruled
out for its online key check). Training takes the user's approval: large downloads and hours of CPU.

- 2026-11-05: the user will test the quick fix on the phone for a few days first, then do the training. The quick fix was left uncommitted at that point.
- 2026-11-05: added opt-in wake clips for that test (`WakeClips`): each wake saves 4 s of 16 kHz WAV, newest 300 kept, only wakes, nothing leaves the phone. Off by default; on with `save_clips` in `shared_prefs/ray_wake_word.xml` (force-stop first, no switch in the app), and the listener's notification says so. Pull with `adb pull /sdcard/Android/data/com.damirl.ray/files/wake-clips`. A listener restarted over adb on a locked phone records (`not silenced`, mic capability present).

## Sources

- One-off test scripts from the session scratchpad, not kept.
- User, chat, 2026-11-05.
- `android/app/src/main/kotlin/com/damirl/ray/assistant/HotwordListenerService.kt`, `WakeWord.kt`, `SpeechGate.kt`.
