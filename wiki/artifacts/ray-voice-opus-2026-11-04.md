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

**Status (2026-11-05): Ray starts 1.9 s sooner on the tunnel.** Opus alone gave 0.8 s on a fast 5 am link: it can only save
the WAV's download, and Piper's own 2.3 s stays. So the app now also splits an answer into pieces and starts on the first
(`SpeechPieces`): 0.71 s against 2.65 s to start the 704-character answer, on the same link, alternating. No listening test
yet, and not yet tried with the helmet worn.

## Pieces

An answer is cut at sentence ends: at least 80 characters first, each next limit 4 times the last. Pieces are fetched in
order, each as soon as the one before is fetched; a new `MediaPlayer` plays each when the last ends. The server didn't change.

| Tunnel, LTE, 2026-11-05 05:20, 5 runs each | Size of what starts | Request to playing |
| --- | --- | --- |
| Pieces (89, 352, 260 characters) | 28 KB | median 0.71 s (0.65-0.73) |
| Whole answer, Opus | 215 KB | median 2.65 s (2.40-2.72) |

- All of it played: 40.93 s in pieces, 40.87 s as one file, so the joins add nothing measurable. By ear: not checked.
- Each next piece was fetched more than 2 s before it was needed. Rule of thumb: Piper makes ~320 characters a second, Ray says ~17.
- A new answer mid-speech: the old answer's later pieces never played. A stopped answer leaves no files (this also ended the
  cache leak noted below).
- The piece no longer holds a line break, so the WAV fallback no longer stops at the first paragraph on the phone.
- Not tried: the server failing mid-answer (by the code, the phone's voice reads the rest).

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
| Tunnel, LTE, 2026-11-05 04:58, 5 runs | Opus | 213 KB | median 2.61 s (2.54-2.82; server 2.31 s) | 40.9 s, the whole answer |
| Tunnel, the same, alternating | WAV | 1.84 MB | median 3.38 s (3.01-4.18; server 2.22 s) | not timed |
| Tunnel, 43 characters, 3 runs each | Opus / WAV | 16 / 132 KB | 0.56 / 0.65 s | |
| Home Wi-Fi, 05:10, 3 runs each | Opus / WAV | 213 / 1841 KB | 2.46 / 2.44 s | |
| Home Wi-Fi, 43 characters, 2 runs each | Opus / WAV | 16 / 134 KB | 0.45 / 0.47 s | |
| Tunnel, LTE, 2026-11-04 23:45, old server, 3 runs | WAV | 1.85 MB | 3.9, 4.0, 4.4 s (server 2.4-2.6 s) | not timed |
| Tunnel, old server refusing Opus, 3 runs | WAV after the 400 | 1.85 MB | 4.1, 4.1, 4.4 s | not timed |
| USB (`adb reverse` to this server code) | Opus | 220 KB | 2.46 s | 41.9 s, the whole answer |
| USB (the same) | WAV | 1.9 MB | 2.44 s | 19.2 s, the first paragraph |
| PC only, medians of 5 | WAV / Opus | 1850 / 212 KB | 2.21 / 2.16 s | |

- The saving can't be bigger than the WAV download: 2.2 s in the helmet re-check (0.8 MB/s), 1.6 s at 23:45 (1.15 MB/s),
  1.2 s at 04:58 (1.6 MB/s). Over the tunnel Opus spends 0.3 s beyond Piper, so a slower link gains more *(inferred: about
  1.9 s at the re-check's speed, not measured on a link that slow)*. Piper's own 2.3 s stays. The first sentence alone takes 0.57 s to make and is 27 KB, so starting Ray before the whole answer is
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

- Before pieces, `PiperAudioPlayer.stop()` didn't delete the audio file: 15 files, 14 MB, from 2-3 November are still in
  the cache, left alone.
- The helmet test page was uncommitted in the main checkout, so these numbers are here.
- `cmd media_session volume --stream 11 --set 0` is silently ignored on this phone: don't count on it to mute a test.
- Two sessions sharing the phone: an APK installed by the other one removes a test build's hook. `MicProbeActivity` with
  an unknown extra starts its default 8 s mic recording, so check the installed APK's hash before a scripted run.

## Related

- [Ray Hybrid WebView Companion and Phone MCP Architecture](../decisions/ray-hybrid-webview-companion-and-phone-mcp.md)

## Sources

1. Runs of 2026-11-04 23:44-23:51 and 2026-11-05 04:57-05:23: the app's `voice_trace.jsonl`, the `strata-server` journal, `dumpsys media.player`,
   driven over adb with a temporary test build (not committed).
2. `~/.local/share/dl-ai/helmet-tests/2026-11-04_201509`: the phone's trace, log and server journal of the 704-character
   answer.
3. Brief from the session "Bluetooth headset activation FIX!", 2026-11-04.
