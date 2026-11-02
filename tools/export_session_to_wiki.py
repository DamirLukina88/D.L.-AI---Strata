#!/usr/bin/env python3
import json
import os
import re
from pathlib import Path

TRANSCRIPT_PATH = str(Path.home() / ".gemini/antigravity/brain/6cda1e32-4945-46c2-ba20-ede82d8daf9e/.system_generated/logs/transcript_full.jsonl")
OUTPUT_PATH = "wiki/artifacts/session-transcript-2026-11-02-companion-handoff.md"

def sanitize(text: str) -> str:
    # Redact actual pairing codes or secrets if present
    text = re.sub(r'pairing code\s+[0-9]{4,8}', 'pairing code [REDACTED]', text, flags=re.I)
    # Sanitize personal home directory paths for pre-commit check
    text = text.replace(str(Path.home()), "~")
    return text

def main():
    turns = []
    if not os.path.exists(TRANSCRIPT_PATH):
        print(f"Transcript not found at {TRANSCRIPT_PATH}")
        return

    with open(TRANSCRIPT_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except Exception:
                continue
            stype = entry.get("type")
            source = entry.get("source")
            created_at = entry.get("created_at", "")
            content = entry.get("content", "")

            if stype == "USER_INPUT" or source == "USER_EXPLICIT":
                if content and not content.startswith("<SYSTEM_MESSAGE>") and not content.startswith("<ADDITIONAL_METADATA>"):
                    clean_content = content
                    if clean_content.startswith("<USER_REQUEST>"):
                        clean_content = clean_content.replace("<USER_REQUEST>", "").replace("</USER_REQUEST>", "").strip()
                    turns.append(("User", created_at, clean_content))
            elif stype == "PLANNER_RESPONSE" and content:
                turns.append(("Ray / Antigravity Agent", created_at, content.strip()))

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as out:
        out.write("""---
title: Session Transcript & Development Handoff: Android Companion & Phone MCP
description: Complete transcript and development handoff of the Ray Android companion app and Phone MCP server session (2026-11-02) for Claude Code.
type: artifact
status: active
tags: [android, companion, handoff, transcript, mcp]
created: 2026-11-02
updated: 2026-11-02
last_verified: 2026-11-02
---

# Session Transcript & Development Handoff: Android Companion & Phone MCP

## 1. Development Handoff to Claude Code

### Executive Summary & Scope
On 2026-11-02, the Ray smartphone companion app was architected, built, and transitioned into a **cached chromeless hybrid Android companion** hosting the complete Strata/D.L. AI Web GUI, supported by a server-side **Phone MCP Server** (`tools/phone_mcp.py`) that gives Ray autonomous hardware control over Xiaomi 17 Ultra (`2512BPNDAG`, Android 17 / HyperOS 3).

### Key Repositories & Working Paths
- **Android App**: `android/` (Kotlin, Jetpack Compose, Android 17 / API 35-37, Gradle 9.1)
- **Web App**: `serve/web/` (`index.html`, `app.js`, `app.css`, `rayface.js`, `speakstream.js`)
- **Server Backend**: `serve/server.py` (Phone bridge `/api/phone/*`, audio endpoints, CLI session proxy)
- **Phone MCP Server**: `tools/phone_mcp.py` (Registered with `dl_sessiond` via `tools/dl_sessiond.py`)
- **Git Commit Checkpoint**: `51b4698a` on branch `main` (`feat(companion): Hybrid chromeless companion WebView & Phone MCP tools`)

---

### Recent User Feedback & Active Issues (Images attached 2026-11-02 21:56 - 21:59)

The user tested the deployed APK on the Xiaomi 17 Ultra and reported 4 issues with screenshots:

#### 1. Top of GUI is broken (Status bar collision)
- **Symptom**: In `RayWebView`, the top header bar (`.st-header` containing Ray logo, tabs, and model select) was pushed under the Android status bar and punch-hole camera.
- **Root Cause**: `MainActivity.kt` calls `enableEdgeToEdge()`, so the window draws behind system bars, while `MainScreen.kt` lacked status bar padding, and CSS `env(safe-area-inset-top)` evaluated to 0px in Android WebView.
- **Status & Fix**:
  - `android/app/src/main/kotlin/com/damirl/ray/ui/main/MainScreen.kt`: Added `.statusBarsPadding().navigationBarsPadding()` to the root container with dark background `Color(0xFF0B0D10)`.
  - `android/app/src/main/kotlin/com/damirl/ray/MainActivity.kt`: Configured `enableEdgeToEdge(statusBarStyle = SystemBarStyle.dark(TRANSPARENT), navigationBarStyle = SystemBarStyle.dark(TRANSPARENT))`.
  - `serve/web/app.css`: Changed `.is-android-companion .st-header` to fixed `padding-top: 8px;` and `.code-mobile-composer` to `padding-bottom: 8px;` to avoid double-padding.

#### 2. App icon should match Ray's red panda branding icon
- **Symptom**: Home screen icon displayed the generic green Android robot with grid (`ic_launcher_background.xml` had `#3DDC84`).
- **Root Cause**: Default template launcher assets were still in place.
- **Status & Fix**:
  - `android/app/src/main/res/drawable/ic_launcher_background.xml`: Updated to solid `#12161B` dark background.
  - Generated full mipmap densities (mdpi, hdpi, xhdpi, xxhdpi, xxxhdpi) of `ic_launcher.webp`, `ic_launcher_round.webp`, and `ic_launcher_foreground.webp` from `serve/web/icon-512.png`.
  - In `HotwordListenerService.kt` and `AudioPlaybackService.kt`: Notification small icon must use `R.drawable.ic_tile_paw` instead of `ic_launcher_foreground`.
  - In `mipmap-anydpi-v26/ic_launcher.xml` and `ic_launcher_round.xml`: Foreground must point to `@mipmap/ic_launcher_foreground`.

#### 3. Ray's voice replies do not work ("SpeechSynthesisUtterance is not defined")
- **Symptom**: Toast error appeared: `CLI session: SpeechSynthesisUtterance is not defined`.
- **Root Cause**: `SpeechSynthesisUtterance` is a browser Web Speech API construct that does NOT exist inside Android WebView (`window.SpeechSynthesisUtterance === undefined`). In `serve/web/app.js`, `TTSController.speakNext()` attempted `new SpeechSynthesisUtterance(chunk)` on line 671 when `this.useServer()` was false or before server TTS was ready, throwing a `ReferenceError`.
- **Status & Fix**:
  - In `serve/web/app.js`: In `speakNext()`, if `typeof window !== "undefined" && window.RayAndroid && typeof window.RayAndroid.speak === "function"`, delegate the chunk directly to `window.RayAndroid.speak(chunk)` and advance `this.currentIndex++`.
  - Guard any usage of `SpeechSynthesisUtterance` with `typeof SpeechSynthesisUtterance !== "undefined"`.
  - In `AudioPlaybackService.kt` and `PiperAudioPlayer.kt`: Verify that `fetchPiperWav` connects properly to `/v1/audio/speech` or falls back cleanly to Android `TextToSpeech` with pitch 1.5.

#### 4. Hold button to activate Ray -> "No speech recognized"
- **Symptom**: Long-pressing power button opened assistant overlay (`RayVoiceSession`), but after 5 seconds it displayed `No speech recognized`.
- **Root Cause**: Google's `SpeechRecognizer` in Android has a 5-second silence timeout. If the user does not begin speaking within 5.0s, or if audio focus was not claimed from the system gesture handler, `SpeechRecognizer.ERROR_NO_MATCH` was returned.
- **Status & Fix**:
  - In `RayVoiceSession.kt`: Request audio focus (`AudioManager.requestAudioFocus`) on show.
  - In `SpeechRecognitionManager.kt`: Add `EXTRA_SPEECH_INPUT_MINIMUM_LENGTH_MILLIS` (4000L), `EXTRA_SPEECH_INPUT_COMPLETE_SILENCE_LENGTH_MILLIS` (3000L), and support multiple locales (`Locale.getDefault().toLanguageTag()` and `en-US`).
  - When `ERROR_NO_MATCH` occurs, display `Tap mic to speak` rather than treating it as a permanent failure, allowing the user to tap the floating mic button to start listening immediately.

---

## 2. Chronological Session Transcript

""")
        for idx, (speaker, ts, text) in enumerate(turns, 1):
            clean_text = sanitize(text)
            out.write(f"### Turn {idx}: {speaker} ({ts})\n\n")
            out.write(f"{clean_text}\n\n---\n\n")

        out.write("""## Sources
- Conversation ID: `6cda1e32-4945-46c2-ba20-ede82d8daf9e`
- Target Device: Xiaomi 17 Ultra (`2512BPNDAG`, Android 17 / HyperOS 3)
- Session Transcript: `.system_generated/logs/transcript_full.jsonl`
- Date: 2026-11-02
""")

    print(f"Successfully exported {len(turns)} conversation turns to {OUTPUT_PATH}")

if __name__ == "__main__":
    main()
