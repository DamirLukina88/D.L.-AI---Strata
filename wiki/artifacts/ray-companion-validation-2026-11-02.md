---
title: "Ray Companion Validation (2026-11-02)"
type: artifact
description: "What was tested on the Xiaomi 17 Ultra over ADB for the Ray Android companion on 2026-11-02 and 03, with results"
status: active
tags: [android, companion, validation]
created: 2026-11-03
updated: 2026-11-03
last_verified: 2026-11-03
---

# Ray Companion Validation (2026-11-02)

## Summary

The Ray Android companion was validated on the Xiaomi 17 Ultra (HyperOS) over wireless ADB with Claude Code, with
the user operating the phone and a Sena helmet intercom. Checks used `adb` (screencap, logcat, dumpsys, appops)
and the WebView DevTools socket (`Runtime.evaluate`).

| Area | Check | Result |
| --- | --- | --- |
| Layout | Top bar below the status bar; keyboard; landscape; camera cutout | Fixed (`safeDrawingPadding`, `adjustResize` on the activity, `configChanges`) |
| Start | White flash on start | Fixed (dark window and WebView background `#0B0D10`) |
| Icon | Launcher icon differs from the web bookmark | Panda with his coffee mug (`make_ray_icons.py --android`) |
| Voice drawer | Opens by long-press, helmet button (after Ray › Always), lock screen | Works; ~1 in 4 triggers on 2026-11-02 opened nothing (logging added, not yet reproduced) |
| Voice drawer | Speech recognized; one retry after 5 s of silence | Works (no silence extras; 400 ms before the retry, else error 11) |
| Helmet | Mic and reply over the headset's call link (SCO) | Works; the helmet's call volume was 1 of 11 (raised on the helmet) |
| Self-listening | Ray never listens while he talks; closing the drawer stops both | Works |
| Fully silent test | Drawer and app with no audio output | Passed |
| Setup screen | Autostart and screen reading detected on HyperOS | Works (app-op 10008; Accessibility › General › Downloaded apps) |
| About tab | "Ray on this phone" card in the app only; app-unused settings hidden; Max tokens gone | Checked in the app and on the website |
| Workspace | Download 2 files at once from the app | Both saved under their own names (DownloadManager 200, SUCCESS); a folder tick selected its 66 files |
| Workspace | Upload several images at once | Fix built (clipData); **needs the user's gallery test** |
| Drawer thinking | `/v1/ray/chat` streams thinking apart from the answer | Server: thinking and answer separate (17 × 3 test); **drawer view needs a spoken test** |
| Drawer panda | Animated panda in the header | Shows and listens (after a 0 px height fix) |
| Tests | Android unit tests | 17 pass |
| Tests | Server unit tests (baseline, before Part B) | 899 run, 1 failure already present (`test_keepawake`), 11 skipped |

Left open: the drawer triggers that opened nothing, the swipe-away fallback (`RayVoiceActivity`) in real use, and
music staying muted in the helmet after a session (helmet side).

## Related

- [Ray Hybrid WebView Companion and Phone MCP Architecture](../decisions/ray-hybrid-webview-companion-and-phone-mcp.md)

## Sources

1. Claude Code session on the phone over ADB, 2026-11-02 and 2026-11-03.
2. User, chat, 2026-11-02: test reports from the helmet and the phone.
