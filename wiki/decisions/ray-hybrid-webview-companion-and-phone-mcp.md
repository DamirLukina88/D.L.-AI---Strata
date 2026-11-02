---
title: "Ray Hybrid WebView Companion and Phone MCP Architecture"
type: decision
description: "Architectural design and implementation of the edge-to-edge Android hybrid companion app and Phone MCP server for Ray"
status: active
tags: [android, companion, webview, mcp, phone-tools, speech, zero-drift]
created: 2026-11-02
updated: 2026-11-02
last_verified: 2026-11-02
---

# Ray Hybrid WebView Companion and Phone MCP Architecture

## Context & Motivation
To eliminate dual-app maintenance drift between the desktop Web App and the Android native client, Ray on Android is architected as an edge-to-edge hardware-accelerated hybrid companion app. The companion loads the full Strata Web App (LAN `http://192.168.3.200:8080` / Remote `https://ai.damir-lukina.com`) within an edge-to-edge chromeless WebView while exposing hardware-level phone capabilities back to Ray's local LLM via MCP (Model Context Protocol).

## Architecture Components

### 1. Edge-to-Edge Android Host (`com.damirl.ray`)
- **`RayWebView.kt`**: Chromeless, hardware-accelerated WebView running with `viewport-fit=cover`. Intercepts back gestures hierarchically (closing web app drawers before navigating back or task-switching). Supports file choosers (`WebChromeClient.FileChooserParams`) for prompt attachments and auto-grants WebRTC audio permissions.
- **`RayNativeBridge.kt`**: `@JavascriptInterface("RayAndroid")` bridge offering:
  - `speak(text, lang)` / `stopSpeaking()`: Native Android TTS delegation.
  - `startListening()` / `stopListening()`: Native SpeechRecognizer speech input.
  - `hapticFeedback(type)`: Subtle haptic feedback for UI interactions.
  - `executeTool(name, argsJson)`: Direct synchronous native tool execution with fallback to broadcast.
- **Background & Wake Services**:
  - `HotwordListenerService.kt`: Persistent wake-word foreground service for hands-free queries.
  - `OnboardingActivity.kt`: Guided HyperOS setup for autostart, battery saver exemption, notification listening, and accessibility permissions.

### 2. Native Phone Tool Categories (`com.damirl.ray.tools`)
- **Device Tools (`DeviceToolsManager.kt`)**: Camera flashlight toggle (`phone_toggle_torch`), battery state (`phone_get_battery`), volume adjustment (`phone_set_volume`), alarm scheduling (`phone_set_alarm`), and app launcher (`phone_launch_app`).
- **Notifications & 2FA (`RayNotificationListenerService.kt`)**: Captures status bar notifications and extracts 4–8 digit verification codes with bilingual Croatian (PBZ, ZABA, Erste, e-Građani, A1, HT) and English regexes (`phone_get_recent_notifications`, `phone_get_2fa_code`).
- **Media Control (`RayMediaController.kt`)**: MediaSessionManager controller to inspect `now_playing` metadata and execute play/pause/next/previous commands (`phone_get_now_playing`, `phone_control_media`).
- **Camera Vision (`CameraVisionManager.kt`)**: Background Camera2 snapshot capturing and JPEG Base64 encoding for multimodal vision prompting (`phone_camera_snap`).
- **Screen Reader (`RayAccessibilityService.kt`)**: Recursive accessibility node tree traversal for reading active on-screen text (`phone_get_screen`).

### 3. Server Relay & MCP Server (`tools/phone_mcp.py`)
- Registered in `~/.config/dl-ai/mcp.json` with auto-activation keywords (`mobitel`, `baterija`, `zvuk`, `svjetlo`, `notifikacije`, `2fa`, `kamera`, `ekran`, `phone`, `torch`, `alarm`).
- Direct bidirectional HTTP relay endpoints in `serve/server.py` (`api/phone/status`, `api/phone/tool/call`, `api/phone/tool/pending`, `api/phone/tool/result`). All endpoints enforce `_authorized()` checking matching the server's API key.
- Fast fallback to ADB command execution when the companion app relay is offline (`is_companion_connected()` returns false), eliminating 6s timeout stalls.
- Automated secrets ingestion: `phone_mcp.py` loads `~/.config/dl-ai/secrets.env` to authenticate transparently.

### 4. Web UI Optimizations (`serve/web/`)
- Injected `.is-android-companion` body class via `checkRayAndroidCompanion()` in `app.js`.
- Responsive CSS safe-area padding (`env(safe-area-inset-top)`, `env(safe-area-inset-bottom)`).
- Prunes redundant desktop-only buttons (`#logout-btn`, `#code-fullscreen-btn`) in companion mode.
- Native STT Integration: Hooks `#code-mobile-mic-btn` to `RayAndroid.startListening()` and `RayAndroid.stopListening()`, ensuring SpeechRecognizer executes safely on Android's Main Looper thread, and handles transcribed results via `window.onRayAndroidSpeechResult`.
- Bidirectional tool relay loop: `startPhoneCompanionBridge()` in `app.js` polls `api/phone/tool/pending`, dispatches execution via `RayAndroid.executeTool()`, and posts results back to `api/phone/tool/result`.
- Navigation loop prevention: Guards `history.replaceState` against spurious re-triggers when switching between web app tabs.

## Validation Status (2026-11-02, Claude Code on the Xiaomi 17 Ultra over ADB)

The handoff listed four issues as fixed; checked against the code and the phone:

- **Status bar overlap: fixed and verified.** The screenshots that showed it came from the APK installed 21:50, before the padding fix (committed 22:10 in `ab4892d3`) was ever built. Header now starts below the 144 px status bar.
- **Launcher icon: fixed and verified** (`98b6a7d1`, `fbbb5ebb`). `ab4892d3` had deleted `drawable/ic_launcher_foreground` while the adaptive icons and two notification builders still used it, so the app did not build. The icon is now Ray holding his mug of cocoa (rayface.js cocoa-break pose), generated by `python3 tools/make_ray_icons.py --android`, so it differs from the web app's bookmark icon. Notifications use `ic_tile_paw`.
- **`SpeechSynthesisUtterance is not defined`: fixed and verified** (`26beed47`). Root cause: `TTSController.init()` returned early when `window.speechSynthesis` was missing (always, in Android WebView), so the server Piper voice was never probed and every reply fell through to the browser voice. Replies now use the server voice through Web Audio like the desktop; the phone's own voice (`RayAndroid.speak` + `isSpeaking()` poll) is only the fallback.
- **"No speech recognized" on power-button hold: fixed** (`e9c63d3f`). `EXTRA_LANGUAGE` was a `Locale` (Google's recognizer logs a ClassCastException and drops it; must be a language-tag String). Google closes the mic 5 s after opening if no speech started; the drawer now listens once more after 0.4 s (restarting immediately fails with error 11, `ERROR_SERVER_DISCONNECTED`), then shows "I didn't catch that". Silent run on the final build (22:39): mic open 11.33 s, retry 16.86 s, idle 21.97 s, about 10.6 s of listening in total. One earlier Assist-key press (22:38) closed the session after 2 s with no app log lines; it did not recur and is unexplained *(possibly the WhatsApp heads-up that arrived then; inferred)*.
- **Gotcha: don't set `EXTRA_SPEECH_INPUT_*_SILENCE_LENGTH_MILLIS`.** Passed as Long they are ignored (Bundle warning: expected Integer); passed as Int, Google's on-device recognizer also applies them to the wait before speech (2000 ms ended a listen after 2 s).
- **Look (2026-11-02):** `RayTheme` is Strata's dark palette from `serve/web/tokens.css` (orange accent `#f97316`), not the template teal. Setup screen and voice drawer restyled; Setup is reachable by long-pressing the app icon ("Setup & permissions", `res/xml/shortcuts.xml`). Voice sessions can be opened for testing with `adb shell input keyevent 219` (Assist key); `cmd voiceinteraction show` is refused without `ACCESS_VOICE_INTERACTION_SERVICE`.

Found and fixed during validation (`fbbb5ebb`):

- **Stacked activities leaked WebViews.** `MainActivity` used the default `standard` launch mode, so launcher, onboarding, hotword-notification and voice-session starts each added an activity with its own live WebView (3 copies, 211 MB PSS after a few relaunches; hidden copies keep running the phone-tool polling loop). Now `singleTask`: 1 activity, 1 WebView after repeated relaunches.
- **Gotcha: `android:windowSoftInputMode` is ignored on `<application>`**; it only works on `<activity>`. With it misplaced the window panned and pushed the header off screen when the keyboard opened. Now on the activity, with `safeDrawingPadding()` on the root Box (bars, camera cutout, keyboard): the page shrinks 805 → 485 CSS px with the keyboard open.
- **Rotation reloaded the web app** (lost drafts and scroll). The activity now declares `configChanges` for orientation, screen size and keyboard; the same page survives rotating.
- `env(safe-area-inset-*)` is 0 in this WebView, so the native padding is the only inset (no double padding).

**Bluetooth headset / helmet (2026-11-02, D.L. SENA intercom):**
- A headset's voice button sends HFP voice recognition, which Android delivers as `VOICE_COMMAND`; only `RayAssistTrampolineActivity` may declare it (opens the drawer). Gotcha: `android:priority` on activity intent filters is ignored for non-system apps, so a duplicate filter on `MainActivity` won.
- Gotcha: Google's `HandsFreeActivity` also handles `VOICE_COMMAND`. The phone keeps a saved "Always" choice (`dumpsys package preferred-xml`); after a filter moves, Android shows a chooser once and the user must pick Ray > Always again.
- The headset mic works only over SCO. `BluetoothMic` makes the SCO device the communication device before listening (checked: `bt_sco_hs`, `SCO_STATE_ACTIVE_INTERNAL`) and releases it 1 s after, so replies play over A2DP. Without it HFP waits 5 s for SCO and the phone mic is used.
- Lock screen: both the helmet button and holding power opened the drawer while locked on HyperOS (no `supportsLaunchVoiceAssistFromKeyguard` needed). The user tested and kept this (chat, 2026-11-02). Risk: anyone holding the locked phone can talk to Ray, whose CLI session may be in YOLO mode.
- Open: about 1 in 4 assistant triggers (22:38, 22:49) got `showSessionForActiveService()` but Ray's session never showed, with no app log lines. Not yet explained.

**Helmet replies and the drawer fallback (2026-11-02, `46473396`):**
- The Sena helmet did not play Ray's answers sent over the music link (A2DP) after a voice session, and once kept music muted while the phone was streaming it (Brave PLAYING, A2DP started, volume 76/150). Since then, after you speak through a headset, Ray answers over its call link (SCO) for 2 min, from both the native voice and the web app's voice (`RayAndroid.holdHeadsetForSpeech`). `BluetoothMic` is one app-wide link held by name (`listen`, `reply`, `web-reply`).
- Gotcha: the call-link volume (`STREAM_VOICE_CALL` for `bt_sco_hs`) was 1 of 11 on this phone, and Android sends it to the headset when the link opens. Raise it with the helmet's volume buttons while Ray speaks.
- Gotcha: `RayVoiceInteractionService.instance` exists only in the process Android bound the service to. After HyperOS's swipe-away kill (`SwipeUpClean`) the next process had no binding (`onBindingDied`), so the trampoline's `showSession` failed. The trampoline now opens `RayVoiceActivity`, the same drawer as an activity (shown over the lock screen). Not reproducible over adb: `am kill` leaves the process alive while the service is bound, and force-stop makes Android rebind at once.
- Drawer show steps are logged (`RayAssistService: onPrepareToShowSession` / `onShowSessionFailed`, `RaySessionService`, `RayVoiceSession: onCreate/onPrepareShow/onShow`) to explain the triggers that opened nothing.

**No self-listening (2026-11-02):** every listen first silences both of Ray's voices (`VoiceOutput.stopAll`: the native `AudioPlaybackService` and the web `TTSController`), and closing, swiping away or leaving the drawer stops listening, drops the pending answer and stops speech (`VoiceDrawerController.close()`). Before, the app's mic button could pick up the drawer's spoken answer and send it back to Ray.

**Setup screen on HyperOS (2026-11-02):** Xiaomi Autostart is app-op 10008 (`adb shell appops get com.damirl.ray` shows `MIUIOP(10008): allow`), readable in the app through the hidden `AppOpsManager.checkOpNoThrow(int, int, String)` (logged as unsupported, not blocked). Screen reading lives at Accessibility, General tab, bottom, **Downloaded apps**, Ray Screen Accessibility; the direct details intent needs `OPEN_ACCESSIBILITY_DETAILS_SETTINGS`, which apps can't hold.

Debugging recipe: debug builds expose `webview_devtools_remote_<pid>`; `adb forward tcp:9333 localabstract:webview_devtools_remote_$(adb shell pidof com.damirl.ray)` then `curl localhost:9333/json` lists every live page (one per WebView) for measuring layout with `Runtime.evaluate`.

## Related
- [Session Transcript & Development Handoff (2026-11-02)](../artifacts/session-transcript-2026-11-02-companion-handoff.md) — Complete transcript and Claude Code technical handoff dossier covering root-cause diagnoses and live verification.

## Sources
- `tools/phone_mcp.py`
- `tools/make_ray_icons.py`
- `android/app/src/main/kotlin/com/damirl/ray/audio/BluetoothMic.kt`
- `android/app/src/main/kotlin/com/damirl/ray/assistant/RayVoiceSession.kt`
- `android/app/src/main/kotlin/com/damirl/ray/audio/SpeechRecognitionManager.kt`
- `android/app/src/main/AndroidManifest.xml`
- ADB and WebView DevTools checks on the Xiaomi 17 Ultra, 2026-11-02
- `tools/test_phone_mcp.py`
- `serve/server.py`
- `serve/web/app.js`
- `serve/web/app.css`
- `android/app/src/main/kotlin/com/damirl/ray/ui/webview/RayWebView.kt`
- `android/app/src/main/kotlin/com/damirl/ray/ui/webview/RayNativeBridge.kt`
- `android/app/src/main/kotlin/com/damirl/ray/tools/`

