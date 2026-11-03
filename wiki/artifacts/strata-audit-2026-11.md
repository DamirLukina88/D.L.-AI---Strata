---
title: "Ray / Strata Audit (2026-11-03)"
type: artifact
description: "Security, correctness, performance and docs audit of the Ray fork after the companion work: what was fixed, what is open, ranked"
status: active
tags: [audit, security, android, server]
created: 2026-11-03
updated: 2026-11-03
last_verified: 2026-11-03
---

# Ray / Strata Audit (2026-11-03)

## Summary

The audit covered the Ray fork's own code: the Android companion, the web app, the server's Ray parts, and the
D.L. CLI tools. The upstream engine and installer were checked but not changed. Seven security problems and five
correctness problems were fixed with tests. Nine items are open and listed below in order of importance.

## Fixed in this audit

| # | Area | Problem | Fix | Proof |
| --- | --- | --- | --- | --- |
| S1 | Android | The `RayAndroid` bridge (API key, phone tools, mic) answered any page in the WebView; the host check was `contains(<domain>)` | Every call checks the page's host against the Strata hosts exactly (`StrataOrigins`) | Unit tests: untrusted page refused, look-alike host refused (`af66bf23`) |
| S2 | Android | `RayToolsReceiver` was exported with no permission: any app could toggle the torch, launch apps or set alarms | Requires `android.permission.DUMP` (the adb shell has it) | adb broadcast still works on the phone (`af66bf23`) |
| S3 | Server | `/api/phone/status`, `/tool/pending` and `/tool/result` let a client without the key through after sending a 401: anyone on the LAN could fake the phone, take pending tool calls (e.g. a 2FA request) or post fake results | All need the key | `serve/test_phone_bridge_auth.py` (fails on the old code); live 401 without key; Ray still reads the battery (`f2b381b1`) |
| S4 | Android | Mic and camera were granted to any page | Strata pages only | (`af66bf23`) |
| S5 | Android | The 2FA code was written to Logcat; transcripts and tool arguments too | Never the code; the rest in debug builds only | (`af66bf23`) |
| S6 | Android | FileProvider shared all of external storage; user-installed CAs were trusted; backups on; setup screen exported | Camera folder only; system CAs only; no backup; not exported | (`af66bf23`) |
| S7 | Repo | The Android example config held the real LAN IP and domain | Placeholders (older pushed commits still contain them, by the user's choice) | (`43c7ee56`) |
| C1 | Phone tools | Volume "10" meant step 10 of 15, not 10% | Always a percent | parity test (`764d3a84`) |
| C2 | Phone tools | The camera tool told Ray he would analyse a photo he never gets | Says the photo stays on the phone | (`764d3a84`) |
| C3 | Web/Android | After the phone's mic the keyboard could stay hidden and the mic button stuck on "recording" | Keyboard and button reset on a result or an error | checked on the phone (`764d3a84`) |
| C4 | MCP | English phone questions never loaded the phone tools (Croatian-only triggers) | `origins`: every prompt from the Android app loads them; English triggers | Ray answered the real battery level (`def1a05b`) |
| C5 | Android | Uploads of several files arrived as one; downloads did nothing in the app | clipData; DownloadManager with the ticket handed over directly | 2 files downloaded with their names (`1296e723`) |

## Open, most important first

1. ~~**Phone tools from the lock screen.**~~ **Fixed 2026-11-03:** `PhoneTools` refuses `phone_get_2fa_code`,
   `phone_get_recent_notifications` and `phone_get_screen` while `KeyguardManager.isDeviceLocked` (unknown counts as
   locked) and tells Ray to ask for an unlock; the other tools still work from the lock screen. 4 unit tests; checked
   unlocked on the phone (the locked case is for the user to try).
2. **The API key travels in plain HTTP on the LAN and is compiled into the APK.** Anyone on the Wi-Fi can read it
   (the phone's second Wi-Fi band had joined the air conditioner's network), and anyone with the APK file has it.
   *Recommendation:* HTTPS on the LAN route too (e.g. the tunnel hostname also at home), or a per-device key the
   setup screen asks for once instead of one in `BuildConfig`.
3. **The bridge is injected into every frame.** The origin check uses the top-level page; a cross-origin iframe on
   a Strata page would pass it. The web app renders no iframes today. *Recommendation:* move the bridge to
   `WebViewCompat.addWebMessageListener` with an origin allow-list.
4. **Cleartext is allowed for every host** (the LAN host comes from `secrets.properties`, which the XML can't read).
   *Recommendation:* generate `network_security_config.xml` at build time with only the LAN host.
5. **Installer and Strata MCP tests fail.** 15 failures and 1 error, the same on the commit before this work
   (`840c30d2`): `tools/test_setup_golden` (expected installer output differs), `test_setup_engine_hash`,
   `test_strata_mcp`. Upstream code; *recommendation:* compare with upstream's current tests before changing them.
6. **"Ok Ray" is only lightly tested.** 1 of 2 synthetic voices from the PC speakers woke the phone; false
   triggers over a day and battery use are not measured.
7. ~~**The assist intent used an older path.**~~ **Fixed 2026-11-03:** the tile already opened the drawer; the main
   app's own assist/voice intents now open it too, and the old ask-and-speak path is gone from the main screen.
8. ~~**The spoken preamble and the answer ran together.**~~ **Fixed 2026-11-03:** `/v1/ray/chat` adds a space when
   text continues after a tool call (streamed and not); `serve/test_ray_chat.py` covers both. Live after the next
   server restart.
9. **The camera tool can't send the photo back.** Honest now; building it needs the photo uploaded to the server
   and passed to the model as an image.

## Performance (no long benchmarks run)

- The app's WebView cleared its cache on every start (`clearCache(true)`); removed 2026-11-03. It made no difference in
  practice: the server sends `Cache-Control: no-cache, no-store` for every file under `/web/`, so nothing is cached
  anyway. Letting the versioned files (`?v=`) be cached would speed up loading; that is upstream's static handler.
- The web page polls `/api/phone/tool/pending` every 1.5 s while the app is open. Fine on Wi-Fi; a long poll would
  save battery.
- The APK is 118 MB: the "Ok Ray" model is about 38 MB of that.
- Speed after a server restart: the first answer is slow while the engine warms up; the next ran at 20.8 tok/s with
  14.1 GB VRAM in use.

## Docs against code

- The README was rewritten for newcomers (100 lines); the detail moved to `docs/RAY_*.md`.
- AGENTS.md says `python tools/test_setup_<name>.py`, but many tools tests only run from the repo root
  (`python -m unittest tools.test_x`); four "failures" in this audit were only that. There is no runner or CI.
  **Fixed 2026-11-03:** `tools/run_tests.sh` runs every suite the right way (tools modules one at a time from the root
  with `tools/` on the path; `--android` adds the app); 6.5 min in all. Only the known installer and Strata MCP
  modules fail.
- Two codebase maps were wrong: `tools/antigravity_local.py` is a symlink to `dl_cli.py`, not a copy, and the
  phone MCP's adb fallback covers all 11 tools.
- The engine's missing `tests/CMakeLists.txt` is upstream's way to default tests off in a release, not a bug.

## Validation

- Server tests: 900 run, all pass (11 skipped).
- Tools tests: 1,246 run; only the 15 failures + 1 error above, all from before this work.
- Android: 19 unit tests pass; lint reports no new issues (43 in the baseline); the UI test compiles (not run:
  it would uninstall the app).
- Web app JS: STT 67/67, sanitizer 10/10, app functions 6/6.
- On the phone: About card, hidden settings, setup screen, voice drawer with panda, downloads, "Ok Ray" once,
  phone tools through Ray (battery level matched the phone twice), wireless adb stable after the Wi-Fi fix.
- Not run: the engine build and its C++ tests (no engine code changed), long benchmarks.

## Related

- [Ray Hybrid WebView Companion and Phone MCP Architecture](../decisions/ray-hybrid-webview-companion-and-phone-mcp.md)
- [Ray Companion Validation (2026-11-02)](ray-companion-validation-2026-11-02.md)
- [GitHub Fork and Public Sanitization Architecture](../decisions/github-fork-and-sanitization.md)

## Sources

1. Claude Code session, 2026-11-02 and 2026-11-03: code reading, tests, and checks on the phone over adb.
2. User, chat, 2026-11-03: the Wi-Fi cause of the adb drops; the audit scope (security, correctness, performance, docs).
