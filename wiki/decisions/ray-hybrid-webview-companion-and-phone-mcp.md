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

## Sources
- `tools/phone_mcp.py`
- `tools/test_phone_mcp.py`
- `serve/server.py`
- `serve/web/app.js`
- `serve/web/app.css`
- `android/app/src/main/kotlin/com/damirl/ray/ui/webview/RayWebView.kt`
- `android/app/src/main/kotlin/com/damirl/ray/ui/webview/RayNativeBridge.kt`
- `android/app/src/main/kotlin/com/damirl/ray/tools/`

