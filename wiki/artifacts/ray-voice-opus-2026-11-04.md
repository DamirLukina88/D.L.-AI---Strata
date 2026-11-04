---
title: "Ray's Voice as Ogg Opus (2026-11-04)"
type: artifact
description: "The phone's Piper voice moves from WAV to Ogg Opus: why, the lost second paragraph, and the tunnel and USB numbers"
status: active
tags: [android, companion, tts, validation]
created: 2026-11-04
updated: 2026-11-04
last_verified: 2026-11-04
---

# Ray's Voice as Ogg Opus (2026-11-04)

## Summary

The app asks for Ogg Opus (`response_format: "opus"`) on every route and falls back to WAV when a server refuses it with
400, so the phone and the server can be updated in either order. It cuts a long answer's download from 1.85 MB to 220 KB
and fixes a bigger problem found on the way: answers were cut off after their first paragraph. Code: branch
`claude/friendly-tereshkova-9694ef`.

**Status (2026-11-04 23:55): Opus over the real tunnel is not measured yet.** That needs the server change running as
`strata-server`. No listening test yet either.

## The lost second paragraph

Piper writes one WAV per line of the text, one after the other, and `MediaPlayer` stops at the end of the first. The
704-character answer from the helmet re-check (two paragraphs, `..._201509`) played 19.0 s of its 42 s, from `tts_play` to
`speak_end`: the whole file was downloaded and the second paragraph was never heard. ffmpeg stops at the same place, so
the server pipes Piper's raw samples (`--output_raw`) into ffmpeg instead of encoding a WAV.

The WAV path is unchanged (old and new `synthesize()` gave the same arguments, stdin and bytes on 20 inputs against a fake
piper), so a multi-line text still stops at its first line in anything that plays it. That covers the phone's WAV fallback
and, *(inferred: not played)*, the web app's chunks of 240 characters or fewer, which can hold a line break.

## Numbers

All on that 704-character answer, 42 s of speech, voice en_US-hfc_male-medium; server on a Ryzen 5 3600, model loaded and
idle; phone a Xiaomi 17 Ultra, debug build.

| Where | Format | Size | Request to playing | Played |
| --- | --- | --- | --- | --- |
| Tunnel, LTE, 23:45, 3 runs | WAV | 1.85 MB | 3.9, 4.0, 4.4 s (server 2.4-2.6 s) | not timed |
| Tunnel, the running server refusing Opus, 3 runs | WAV after the 400 | 1.85 MB | 4.1, 4.1, 4.4 s | not timed |
| USB (`adb reverse` to this server code) | Opus | 220 KB | 2.46 s | 41.9 s, the whole answer |
| USB (the same) | WAV | 1.9 MB | 2.44 s | 19.2 s, the first paragraph |
| PC only, medians of 5 | WAV / Opus | 1850 / 212 KB | 2.21 / 2.16 s | |

- The saving can't be bigger than the WAV download: 2.2 s in the helmet re-check (0.8 MB/s), 1.6 s at 23:45 (1.15 MB/s). Piper's
  own 2.4 s stays. The first sentence alone takes 0.57 s to make and is 27 KB, so starting Ray before the whole answer is
  ready is what could cut the wait further.
- During Opus, `dumpsys media.player` shows `audio/opus`, `c2.android.opus.decoder`, offloading 0, speed 1.05 and stream 11
  (assistant). Pitch is set in the same call as speed.
- Encoding after Piper added 0.15-0.41 s. Encoding while Piper speaks adds none that can be measured.

## Why these settings

- Opus at 32k, effort 5: 1.0-1.2 dB from the original in every Bark band. Effort 10 at the same size (40k, 200 KB) is 0.2 dB
  closer below 2.7 kHz but 1.6-2.3 dB off above it, where consonants are and where Ray's pitch of 1.5 moves more of his voice.
- The "voip" mode was further off than "audio". MP3, AAC and Vorbis were further off for their size. FLAC only halves it.
- Whisper (base) heard the same 129 words in the original and the Opus file.

## Gotchas

- `PiperAudioPlayer.stop()` doesn't delete the audio file: each interrupted answer leaves its file in the app's cache (15
  files, 14 MB, from 2-3 November).
- The helmet test page was uncommitted in the main checkout, so these numbers are here.

## Related

- [Ray Hybrid WebView Companion and Phone MCP Architecture](../decisions/ray-hybrid-webview-companion-and-phone-mcp.md)

## Sources

1. Runs of 2026-11-04 23:44-23:51: the app's `voice_trace.jsonl`, the `strata-server` journal, `dumpsys media.player`,
   driven over adb with a temporary test build (not committed).
2. `~/.local/share/dl-ai/helmet-tests/2026-11-04_201509`: the phone's trace, log and server journal of the 704-character
   answer.
3. Brief from the session "Bluetooth headset activation FIX!", 2026-11-04.
