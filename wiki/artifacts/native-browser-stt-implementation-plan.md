---
title: "Native Browser STT Implementation Plan"
type: artifact
description: "Architecture, design specs, and implementation plan for native browser Speech-to-Text (STT) across desktop and mobile browsers."
status: active
tags: [web, stt, speech, plan, android, brave, chrome]
created: 2026-10-17
updated: 2026-10-17
last_verified: 2026-10-17
---

# Native Browser STT Implementation Plan

## Goal Description
Implement an ultra-responsive, zero-latency, client-side Speech-to-Text (STT) dictation engine for D.L. AI / Strata across both **App Chat** (`#view-chat`) and **Code Chat** (`#view-code`).

The solution operates entirely within the browser via the native Web Speech API (`webkitSpeechRecognition` / `SpeechRecognition`), providing real-time live streaming transcription directly into the message composer as words are spoken. It requires zero server compute, zero Python dependencies, and zero disk space overhead.

### Target Platforms & Compatibility
- **Desktop Google Chrome / Chromium**: Native, zero-setup, real-time live transcription with interim word streaming.
- **Android Google Chrome**: Native Android speech recognition via system microphone permissions with instant interim streaming.
- **Desktop Brave Browser**: Full compatibility supported via an automatic step-by-step guide dialog instructing the user to enable *"Use Google Services for speech recognition"* in `brave://settings/system`.
- **Android Brave Browser**: Step-by-step mobile settings guidance for microphone permissions and speech services.

---

## Architecture & Interaction Design

```mermaid
flowchart TD
    subgraph UI ["User Interface Controls"]
        MIC["Microphone Button (#mic-btn, #code-mobile-mic-btn)"]
        AS_GUI["Composer Auto-Send Toggle (#auto-send-btn)"]
        AS_SET["About Settings: Auto-send on speech pause"]
        LANG["Language Selector (About Settings)"]
        TEXT["Composer Textarea (#input, #code-mobile-input)"]
    end

    subgraph Controller ["STTController (Client Engine)"]
        DETECT["Browser & Brave Service Detector"]
        RECOG["SpeechRecognition / webkitSpeechRecognition"]
        INTERIM["Interim Stream Buffer (Live Words)"]
        TIMER["Silence Watchdog (Auto-stop on 4s silence)"]
        GUIDE["Brave Setup Modal (#brave-stt-dialog)"]
    end

    MIC -->|Tap (Toggle) or Hold (PTT)| Controller
    AS_GUI <-->|Bidirectional Sync| AS_SET
    LANG -->|Locale (e.g. en-US, de-DE)| Controller

    Controller --> DETECT
    DETECT -->|Service Blocked| GUIDE
    DETECT -->|Service Ready| RECOG

    RECOG -->|Interim Results| INTERIM
    INTERIM -->|Live Visual Stream| TEXT
    RECOG -->|Finalized Result| TIMER

    TIMER -->|Auto-Send Enabled| SEND["send() / codeSend()"]
    TIMER -->|Auto-Send Disabled| IDLE["Keep Text in Box for User Review"]
```

### Speech Lifecycle State Machine

1. **Idle State**: Microphone button displays standard mic icon (`i-mic`). Composer is in normal text entry mode.
2. **Listening State (`.is-recording`)**:
   - Microphone button turns active with a pulsing red aura (`box-shadow` ripple animation).
   - Icon switches to active microphone / stop square.
   - Textarea placeholder updates to *"Listening... Speak your prompt"*.
3. **Interim Streaming**:
   - As words are spoken, `recognition.onresult` streams live uncommitted words into the textarea with clear visual cursor feedback.
4. **Finalization & Silence Detection**:
   - When the speaker finishes a sentence, `result.isFinal` commits the text cleanly.
   - An automatic 4-second silence timer stops the microphone cleanly if the user stops speaking.
5. **Post-Speech Action**:
   - **If Auto-Send is OFF**: Microphone turns off; finalized text remains in the textarea, ready for user review, manual editing, or clicking Send.
   - **If Auto-Send is ON**: A brief grace period allows the user to review the final transcription before `send()` automatically fires.

---

## Implemented Components

### Component 1: SVG Icons (`serve/web/sprite.svg`)
- Added `<symbol id="i-mic">` (Microphone).
- Added `<symbol id="i-mic-off">` (Muted / disabled microphone).
- Added `<symbol id="i-auto-send">` (Bolt / automated submission lightning indicator).

### Component 2: Core Speech-to-Text Controller (`STTController` in `serve/web/app.js`)
- **Recognition Instance**: `new (window.SpeechRecognition || window.webkitSpeechRecognition)()`
- **Configuration**: `continuous = true`, `interimResults = true`, `lang = store.get("stt_lang", navigator.language || "en-US")`.
- **Dual-Mode Interaction**:
  - Click / tap initiates recording. Click again stops recording.
  - Pointerdown + hold (>400ms) activates Push-to-Talk (auto-stops on pointerup).
- **Auto-Send State Management**: Synchronized via `store.get("stt_auto_send", false)`.
- **Brave Detection & Error Handling**: Catches `service-not-allowed` or `network` errors and automatically opens `#brave-stt-dialog`.

### Component 3: App Chat Composer GUI Integration (`serve/web/index.html` & `serve/web/app.js`)
- Added `#auto-send-btn` and `#mic-btn` to the composer bar before `#send-btn`.

### Component 4: Code Chat Mobile Input GUI Integration (`serve/web/index.html` & `serve/web/app.js`)
- Added `#code-mobile-mic-btn` right next to `#code-mobile-send-btn`.

### Component 5: Settings & Brave Guide Modal (`serve/web/index.html`, `serve/web/app.js`, `serve/web/app.css`)
- Extended Voice card in About settings with recognition language dropdown and auto-send toggle.
- Added `#brave-stt-dialog` modal with clipboard copy button for `brave://settings/system`.

### Component 6: CSS Styling (`serve/web/app.css`)
- Added `.st-btn.is-recording` red pulse animation (`@keyframes st-mic-pulse`).
- Added `.composer-action-btn.is-active` accent state for auto-send.

---

## Sources

- W3C Web Speech API Specification.
- User chat session, 2026-10-17.
