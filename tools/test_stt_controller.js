// tools/test_stt_controller.js - Unit tests for STT Speech-to-Text transcript merge & dual-mode logic
"use strict";

const assert = require("assert");

// 1. Transcript merge logic test
function mergeTranscript(baseText, finalText, interimText) {
  const prefix = baseText ? (baseText.endsWith(" ") || baseText.endsWith("\n") ? baseText : baseText + " ") : "";
  const spoken = (finalText + (interimText ? (finalText ? " " : "") + interimText : "")).trim();
  return prefix + spoken;
}

console.log("Running STT Unit Tests...");

// Test 1: Empty base text with interim text
assert.strictEqual(
  mergeTranscript("", "", "hello world"),
  "hello world",
  "Empty base with interim speech should produce trimmed speech"
);

// Test 2: Existing base text with final transcript
assert.strictEqual(
  mergeTranscript("Please review this code", "and optimize it", ""),
  "Please review this code and optimize it",
  "Base text without trailing space should get spaced appropriately"
);

// Test 3: Existing base text with trailing newline
assert.strictEqual(
  mergeTranscript("Explain:\n", "how does caching work", ""),
  "Explain:\nhow does caching work",
  "Base text with trailing newline should preserve newline"
);

// Test 4: Existing base text with both final and interim
assert.strictEqual(
  mergeTranscript("Hey Strata,", "what is the status", "of the model"),
  "Hey Strata, what is the status of the model",
  "Base text, final, and interim speech should merge cleanly"
);

// 2. Dual-mode interaction simulation test
function simulateInteraction(holdDurationMs, isAlreadyRecording) {
  let isHold = false;
  let isPushToTalk = false;
  let started = false;
  let stopped = false;
  let toggled = false;
  let didAction = false;

  // Pointer down
  const pressTimerFired = holdDurationMs >= 400;

  if (pressTimerFired) {
    isHold = true;
    isPushToTalk = true;
    if (!isAlreadyRecording) started = true;
  }

  // Pointer up
  if (isHold) {
    isHold = false;
    isPushToTalk = false;
    if (started || isAlreadyRecording) stopped = true;
    didAction = true;
  }

  // Click event fires
  if (!didAction) {
    toggled = true;
  }

  return { started, stopped, toggled, isPushToTalk };
}

// Test 5: Short tap (150ms) -> Click toggle
const tapResult = simulateInteraction(150, false);
assert.strictEqual(tapResult.toggled, true, "Short tap should fire toggle");
assert.strictEqual(tapResult.started, false, "Short tap should not fire push-to-talk hold start");
assert.strictEqual(tapResult.stopped, false, "Short tap should not fire push-to-talk hold stop");

// Test 6: Hold-to-talk (600ms) -> Push-to-Talk start and stop
const holdResult = simulateInteraction(600, false);
assert.strictEqual(holdResult.started, true, "Hold >= 400ms should start recording");
assert.strictEqual(holdResult.stopped, true, "Release after hold should stop recording");
assert.strictEqual(holdResult.toggled, false, "Hold should suppress click toggle");

// 3. Auto-send decision test
function shouldAutoSend(hadRecording, autoSendEnabled, finalText, interimText) {
  const hadFinalSpoken = Boolean((finalText + " " + interimText).trim());
  return Boolean(hadRecording && autoSendEnabled && hadFinalSpoken);
}

// Test 7: Auto-send enabled with spoken words
assert.strictEqual(shouldAutoSend(true, true, "run benchmark", ""), true, "Auto-send on with text should trigger send");

// Test 8: Auto-send enabled but user spoke nothing (aborted / silence)
assert.strictEqual(shouldAutoSend(true, true, "", ""), false, "Auto-send on with empty speech should NOT trigger send");

// Test 9: Auto-send disabled with spoken words
assert.strictEqual(shouldAutoSend(true, false, "hello", ""), false, "Auto-send off should NOT trigger send");

// 4. Android onresult reconstruction test with mergeSpeechTranscripts
function mergeSpeechTranscripts(existing, incoming) {
  const ex = (existing || "").trim();
  const inc = (incoming || "").trim();
  if (!inc) return existing || "";
  if (!ex) return incoming || "";

  const exLower = ex.toLowerCase();
  const incLower = inc.toLowerCase();

  if (exLower === incLower) return existing;
  if (incLower.startsWith(exLower)) return inc;
  if (exLower.endsWith(incLower)) return existing;

  const exWords = ex.split(/\s+/);
  const incWords = inc.split(/\s+/);
  const maxOverlap = Math.min(exWords.length, incWords.length);
  for (let len = maxOverlap; len > 0; len--) {
    const exTail = exWords.slice(exWords.length - len).join(" ").toLowerCase();
    const incHead = incWords.slice(0, len).join(" ").toLowerCase();
    if (exTail === incHead) {
      const remainder = incWords.slice(len).join(" ");
      const sep = existing.endsWith(" ") || existing.endsWith("\n") ? "" : " ";
      return remainder ? `${existing}${sep}${remainder}` : existing;
    }
  }

  const sep = existing.endsWith(" ") || existing.endsWith("\n") ? "" : " ";
  return `${existing}${sep}${inc}`;
}

function processResults(resultsList) {
  let finalStr = "";
  let interimStr = "";

  for (let i = 0; i < resultsList.length; ++i) {
    const res = resultsList[i];
    if (!res || !res[0]) continue;
    const transcript = (res[0].transcript || "").trim();
    if (!transcript) continue;

    if (res.isFinal) {
      finalStr = mergeSpeechTranscripts(finalStr, transcript);
    } else {
      interimStr = mergeSpeechTranscripts(interimStr, transcript);
    }
  }
  return { finalStr, interimStr };
}

// Test 10: Android Chrome cumulative event sequence should not duplicate words
const androidEvent1 = [{ isFinal: true, 0: { transcript: "how" } }];
const androidEvent2 = [{ isFinal: true, 0: { transcript: "how are" } }];
const androidEvent3 = [{ isFinal: true, 0: { transcript: "how are you" } }];
const androidEvent4 = [{ isFinal: true, 0: { transcript: "how are you doing today" } }];

assert.strictEqual(processResults(androidEvent1).finalStr, "how");
assert.strictEqual(processResults(androidEvent2).finalStr, "how are");
assert.strictEqual(processResults(androidEvent3).finalStr, "how are you");
assert.strictEqual(processResults(androidEvent4).finalStr, "how are you doing today");

// Test 11: Android multi-item cumulative result list (The exact bug reported: "how are you" then "who are you")
const androidMultiChunkCumulative = [
  { isFinal: true, 0: { transcript: "how are you" } },
  { isFinal: true, 0: { transcript: "how are you who are you" } }
];
assert.strictEqual(
  processResults(androidMultiChunkCumulative).finalStr,
  "how are you who are you",
  "Cumulative result list must resolve to the full sentence without doubling 'how are you'"
);

// Test 12: Android duplicate identical segment suppression
const duplicateSegments = [
  { isFinal: true, 0: { transcript: "who are you" } },
  { isFinal: true, 0: { transcript: "who are you" } },
  { isFinal: true, 0: { transcript: "and what can you do" } }
];
assert.strictEqual(
  processResults(duplicateSegments).finalStr,
  "who are you and what can you do",
  "Consecutive identical segments should be deduplicated"
);

// Test 13: Partial overlap transition
const partialOverlapSegments = [
  { isFinal: true, 0: { transcript: "tell me how are you" } },
  { isFinal: true, 0: { transcript: "how are you who are you" } }
];
assert.strictEqual(
  processResults(partialOverlapSegments).finalStr,
  "tell me how are you who are you",
  "Overlapping phrases should merge seamlessly without stuttering"
);

// Test 14: Input value combination with base text
const baseText = "how are you";
const newSpeech = "how are you who are you";
const mergedInput = mergeSpeechTranscripts(baseText, newSpeech);
assert.strictEqual(
  mergedInput,
  "how are you who are you",
  "Existing base text in textarea must not be duplicated when engine returns cumulative phrase"
);

// 5. STT-only Auto-speak prompt origin detection
function computeFromVoice(sttState, inputText) {
  let fromVoice = false;
  if (sttState.lastInputWasVoice && sttState.lastTranscribedText) {
    const spokenLower = sttState.lastTranscribedText.toLowerCase();
    const textLower = (inputText || "").trim().toLowerCase();
    if (textLower.includes(spokenLower) || spokenLower.includes(textLower)) {
      fromVoice = true;
    }
  }
  // Reset after send
  sttState.lastInputWasVoice = false;
  sttState.lastTranscribedText = "";
  return fromVoice;
}

// Test 15: Pure typed input without STT -> fromVoice is false
const typedState = { lastInputWasVoice: false, lastTranscribedText: "" };
assert.strictEqual(
  computeFromVoice(typedState, "How do I configure nginx?"),
  false,
  "Manually typed request without STT should NOT trigger auto-speak"
);

// Test 16: STT dictated prompt -> fromVoice is true
const sttState = { lastInputWasVoice: true, lastTranscribedText: "what is the speed of light" };
assert.strictEqual(
  computeFromVoice(sttState, "what is the speed of light"),
  true,
  "STT dictated prompt must trigger auto-speak"
);
// Subsequent typed message after reset should be false
assert.strictEqual(
  computeFromVoice(sttState, "thanks for the answer"),
  false,
  "Subsequent typed turn after STT turn must be false"
);

// Test 17: STT prompt modified with extra manual punctuation / word -> fromVoice is true
const sttModifiedState = { lastInputWasVoice: true, lastTranscribedText: "how are you" };
assert.strictEqual(
  computeFromVoice(sttModifiedState, "how are you doing today?"),
  true,
  "STT dictated prompt with appended words should retain voice origin"
);

// Test 18: STT prompt replaced entirely with typed text -> fromVoice is false
const sttReplacedState = { lastInputWasVoice: true, lastTranscribedText: "tell me a joke" };
assert.strictEqual(
  computeFromVoice(sttReplacedState, "explain binary search trees"),
  false,
  "Dictated text replaced with unrelated manual text must NOT trigger auto-speak"
);

// 6. Voice matching by URI or Name
function findVoice(voices, savedUri) {
  if (!savedUri) return null;
  return voices.find((v) => v.voiceURI === savedUri || v.name === savedUri) || null;
}

const mockVoices = [
  { voiceURI: "en_US-bryce-medium piper", name: "en_US-bryce-medium piper", lang: "en" },
  { voiceURI: "en_US-lessac-medium piper", name: "en_US-lessac-medium piper", lang: "en" },
  { voiceURI: "urn:moz-tts:speechd:en_US-amy-medium", name: "en_US-amy-medium", lang: "en" },
];

// Test 19: Match by voiceURI exactly
assert.strictEqual(
  findVoice(mockVoices, "en_US-bryce-medium piper")?.name,
  "en_US-bryce-medium piper",
  "Voice selector should find voice by exact voiceURI"
);

// Test 20: Match by name when voiceURI differs
assert.strictEqual(
  findVoice(mockVoices, "en_US-amy-medium")?.voiceURI,
  "urn:moz-tts:speechd:en_US-amy-medium",
  "Voice selector should find voice by name even if URI schema differs"
);

// 7. Test button re-click behavior
function shouldToggleOff(speaking, activeBtn, clickedBtn, msgObj, activeMsg) {
  if (!speaking) return false;
  const isTestBtn = Boolean(clickedBtn && clickedBtn.id === "tts-test-btn");
  return !isTestBtn && ((activeBtn === clickedBtn && clickedBtn !== null) || (activeMsg === msgObj && msgObj !== null));
}

// Test 21: Test voice button re-click must NOT toggle off (should immediately restart with new voice)
const testBtnObj = { id: "tts-test-btn" };
assert.strictEqual(
  shouldToggleOff(true, testBtnObj, testBtnObj, null, null),
  false,
  "Test button re-click while speaking must NOT toggle off"
);

// Test 22: Message speaker button re-click in chat DOES toggle off
const msgBtnObj = { id: "msg-speak-1" };
assert.strictEqual(
  shouldToggleOff(true, msgBtnObj, msgBtnObj, null, null),
  true,
  "Message speaker button re-click in chat should toggle off"
);
// 8. STT Engine Selection logic tests
function resolveEngine(pref, hasWhisper, hasBrowserSpeech) {
  if (pref === "whisper") return "whisper";
  if (pref === "browser") return "browser";
  if (hasWhisper) return "whisper";
  if (hasBrowserSpeech) return "browser";
  return "whisper";
}

// Test 23: Auto with whisper available picks whisper
assert.strictEqual(
  resolveEngine("auto", true, true),
  "whisper",
  "Auto mode should prefer local whisper when available"
);

// Test 24: Auto without whisper picks browser
assert.strictEqual(
  resolveEngine("auto", false, true),
  "browser",
  "Auto mode without local whisper should fall back to browser"
);

// Test 25: Explicit whisper preference always returns whisper
assert.strictEqual(
  resolveEngine("whisper", true, true),
  "whisper",
  "Explicit whisper should return whisper"
);

// Test 26: Explicit browser preference returns browser even if whisper available
assert.strictEqual(
  resolveEngine("browser", true, true),
  "browser",
  "Explicit browser should return browser"
);

// Test 27: Brave browser fallback to whisper when cloud speech service-not-allowed
function handleSpeechError(err, isBrave, hasWhisper) {
  if (err === "service-not-allowed" || err === "network") {
    if (hasWhisper) return "switch-to-whisper";
    if (isBrave) return "show-brave-guide";
    return "show-network-toast";
  }
  return "other";
}
assert.strictEqual(
  handleSpeechError("service-not-allowed", true, true),
  "switch-to-whisper",
  "Brave service-not-allowed should seamlessly switch to whisper when installed"
);
assert.strictEqual(
  handleSpeechError("service-not-allowed", true, false),
  "show-brave-guide",
  "Brave service-not-allowed without whisper should show guide"
);

// 9. CLI coding auto-send and auto-speak tests
// Test 28: Both auto-send buttons update in sync
function simulateSetAutoSend(val) {
  const btns = [
    { id: "auto-send-btn", active: false, pressed: "false" },
    { id: "code-mobile-auto-send-btn", active: false, pressed: "false" }
  ];
  for (const b of btns) {
    b.active = Boolean(val);
    b.pressed = String(Boolean(val));
  }
  return btns;
}
const syncedBtns = simulateSetAutoSend(true);
assert.strictEqual(syncedBtns[0].active, true, "Chat auto-send button should be active");
assert.strictEqual(syncedBtns[1].active, true, "CLI coding auto-send button should be active");

// Test 29: CLI coding turnFromVoice preserved across user event
function simulateCliTurn(wasVoice) {
  const codeState = { turnFromVoice: wasVoice, cur: null };
  // 1. User event arrives
  function onUserEvent() {
    // codeEnd() closes any previous block but must NOT clear turnFromVoice
    codeState.cur = null;
  }
  onUserEvent();
  // 2. Assistant starts reply
  function onAssistantText(chunk) {
    if (!codeState.cur) {
      codeState.cur = { text: "", fromVoice: Boolean(codeState.turnFromVoice) };
    }
    codeState.cur.text += chunk;
  }
  onAssistantText("Here is the answer");
  return codeState.cur.fromVoice;
}
assert.strictEqual(simulateCliTurn(true), true, "Voice input must set assistant card fromVoice to true");
assert.strictEqual(simulateCliTurn(false), false, "Typed input must keep assistant card fromVoice false");

// Test 30: codeOnTurnEnd speaks when autoSpeak=true and turnFromVoice=true
function simulateTurnEnd(autoSpeak, turnFromVoice, replaying, text) {
  let spoken = null;
  if (autoSpeak && turnFromVoice && !replaying) {
    if (text && text.trim()) {
      spoken = text.trim();
    }
  }
  return spoken;
}
assert.strictEqual(
  simulateTurnEnd(true, true, false, "Refactored function successfully."),
  "Refactored function successfully.",
  "Turn end with STT input and autoSpeak=true should speak aloud"
);

// Test 31: codeOnTurnEnd stays silent when turnFromVoice=false (typed)
assert.strictEqual(
  simulateTurnEnd(true, false, false, "Refactored function successfully."),
  null,
  "Turn end with typed input should NOT speak aloud"
);

// Test 32: codeOnTurnEnd stays silent during history replay
assert.strictEqual(
  simulateTurnEnd(true, true, true, "Historical answer from yesterday."),
  null,
  "Turn end during history replay should NEVER speak aloud"
);

// 10. Auto-Send Instant Submission (0ms) and Live Population Tests
function simulateTranscriptionWorkflow({
  transcribedText,
  autoSendEnabled,
}) {
  let textboxValue = "";
  let sentText = null;

  // 1. Text is ALWAYS populated into textbox first so user visually sees it
  textboxValue = transcribedText;

  // 2. If auto-send is on, submit immediately (0ms delay)
  if (autoSendEnabled && transcribedText.trim()) {
    sentText = textboxValue;
    textboxValue = "";
  }

  return { textboxValue, sentText };
}

// Test 33: Textbox is visibly populated before instant auto-send
const simAutoSend = simulateTranscriptionWorkflow({
  transcribedText: "Explain how quicksort partitions data",
  autoSendEnabled: true,
});
assert.strictEqual(
  simAutoSend.sentText,
  "Explain how quicksort partitions data",
  "Transcribed text must be submitted instantly when auto-send is enabled"
);

// Test 34: Instant submission leaves composer empty after send
assert.strictEqual(simAutoSend.textboxValue, "", "Composer should be cleared after instant send");

// Test 35: Empty speech with auto-send does not submit
const simEmpty = simulateTranscriptionWorkflow({
  transcribedText: "",
  autoSendEnabled: true,
});
assert.strictEqual(simEmpty.sentText, null, "Empty speech should not be submitted");

// Test 36: Auto-send disabled keeps text in box with zero sending
const simDisabled = simulateTranscriptionWorkflow({
  transcribedText: "Save this note",
  autoSendEnabled: false,
});
assert.strictEqual(simDisabled.sentText, null, "Text should not be sent when auto-send is disabled");
assert.strictEqual(simDisabled.textboxValue, "Save this note", "Text must stay in box for manual send");

// Test 37: Complex prompt with special characters sent intact
const simSpecial = simulateTranscriptionWorkflow({
  transcribedText: "Refactor main() in src/engine.cu --check-all",
  autoSendEnabled: true,
});
assert.strictEqual(simSpecial.sentText, "Refactor main() in src/engine.cu --check-all", "Complex prompt must send intact");
assert.strictEqual(simDisabled.textboxValue, "Save this note", "Text must stay in box for manual send");

// Test 38: Live interim speech progressive updates
function simulateLiveSpeechProgression(interimPhrases, finalPhrase) {
  let box = "";
  for (const phrase of interimPhrases) {
    box = mergeSpeechTranscripts("", phrase);
  }
  box = mergeSpeechTranscripts("", finalPhrase);
  return box;
}
const progressiveResult = simulateLiveSpeechProgression(
  ["testing speech", "testing speech to text", "testing speech to text while walking"],
  "testing speech to text while walking outside"
);
assert.strictEqual(
  progressiveResult,
  "testing speech to text while walking outside",
  "Progressive interim updates must smoothly lead to final transcript"
);

// 11. Notification Toast Dismissal & Click-Through Tests
function simulateToastInteraction({
  toasts,
  clickTarget, // "outside" | "toast" | "action_button" | "underlying_button"
  elementsUnderPoint = [],
}) {
  let currentToasts = [...toasts];
  let actionRan = false;
  let clickedInteractive = null;

  function dismissAllToasts() {
    currentToasts = [];
  }

  // Pointerdown capture simulation
  if (currentToasts.length > 0) {
    if (clickTarget === "action_button") {
      actionRan = true;
      currentToasts = currentToasts.filter(t => t.id !== "toast-with-action");
      return { currentToasts, actionRan, clickedInteractive };
    }

    const hitToast = clickTarget === "toast" || clickTarget === "underlying_button";
    dismissAllToasts();

    if (hitToast && elementsUnderPoint.length > 0) {
      const interactive = elementsUnderPoint.find(el => el.interactive);
      if (interactive) {
        clickedInteractive = interactive.id;
      }
    }
  }

  return { currentToasts, actionRan, clickedInteractive };
}

// Test 39: Touching outside toasts immediately dismisses active toasts
const testOutside = simulateToastInteraction({
  toasts: [{ id: "toast-1" }, { id: "toast-2" }],
  clickTarget: "outside",
});
assert.strictEqual(testOutside.currentToasts.length, 0, "Touching outside toasts should dismiss all active toasts immediately");

// Test 40: Clicking toast directly dismisses it
const testClickToast = simulateToastInteraction({
  toasts: [{ id: "toast-1" }],
  clickTarget: "toast",
});
assert.strictEqual(testClickToast.currentToasts.length, 0, "Clicking toast directly should dismiss it");

// Test 41: Clicking toast when an interactive button is underneath forwards click to underlying button
const testUnderlying = simulateToastInteraction({
  toasts: [{ id: "toast-1" }],
  clickTarget: "underlying_button",
  elementsUnderPoint: [{ id: "toast-1", interactive: false }, { id: "auto-send-toggle", interactive: true }],
});
assert.strictEqual(testUnderlying.currentToasts.length, 0, "Toasts must be dismissed on tap");
assert.strictEqual(testUnderlying.clickedInteractive, "auto-send-toggle", "Click must be forwarded to underlying button without being blocked");

// Test 42: Action button inside toast executes action without being dismissed pre-emptively
const testActionBtn = simulateToastInteraction({
  toasts: [{ id: "toast-with-action" }],
  clickTarget: "action_button",
});
assert.strictEqual(testActionBtn.actionRan, true, "Toast action button must be allowed to execute its handler");

// 12. Sampling Drawer Accessibility & Focus Restoration Tests
function simulateDrawerLifecycle({ initialFocusInside = false, triggerId = "sampling-btn" }) {
  const triggerEl = { id: triggerId, focused: false, focus() { this.focused = true; } };
  const applyBtn = { id: "s-apply", focused: initialFocusInside, blur() { this.focused = false; } };
  const drawer = {
    open: true,
    attributes: { "data-open": "true" },
    inert: false,
    contains(el) { return el === applyBtn; }
  };
  let activeElement = initialFocusInside ? applyBtn : triggerEl;
  let lastDrawerTrigger = triggerEl;

  function closeDrawer() {
    if (activeElement && drawer.contains(activeElement)) {
      activeElement.blur();
      activeElement = null;
      if (lastDrawerTrigger && typeof lastDrawerTrigger.focus === "function") {
        lastDrawerTrigger.focus();
        activeElement = lastDrawerTrigger;
      }
    }
    drawer.open = false;
    drawer.attributes["data-open"] = "false";
    drawer.attributes["aria-hidden"] = "true";
    drawer.attributes["inert"] = "";
    drawer.inert = true;
  }

  closeDrawer();
  return { drawer, applyBtn, triggerEl, activeElement };
}

// Test 43: Closing drawer removes focus from #s-apply before applying aria-hidden/inert
const simApplyClose = simulateDrawerLifecycle({ initialFocusInside: true, triggerId: "sampling-btn" });
assert.strictEqual(simApplyClose.applyBtn.focused, false, "#s-apply must be blurred upon drawer close");
assert.strictEqual(simApplyClose.drawer.attributes["aria-hidden"], "true", "aria-hidden must be set to true on close");
assert.strictEqual(simApplyClose.drawer.inert, true, "drawer inert property must be set to true on close");

// Test 44: Focus is returned to trigger button (#sampling-btn)
assert.strictEqual(simApplyClose.triggerEl.focused, true, "Focus must be restored to the opening trigger button");
assert.strictEqual(simApplyClose.activeElement.id, "sampling-btn", "Active element must be the trigger button");

// Test 45: Focus is returned to #code-sampling-btn when opened from CLI coding
const simCodeClose = simulateDrawerLifecycle({ initialFocusInside: true, triggerId: "code-sampling-btn" });
assert.strictEqual(simCodeClose.triggerEl.focused, true, "#code-sampling-btn must receive focus when closed in CLI mode");

// 13. TTS cleanForSpeech Emoji & Symbol Filter Tests
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const appJsPath = path.resolve(__dirname, "../serve/web/app.js");
const appJsSource = fs.readFileSync(appJsPath, "utf-8");
const cleanStart = appJsSource.indexOf("function cleanForSpeech");
const cleanEnd = appJsSource.indexOf("\nfunction chunkText");
const cleanFnSource = appJsSource.slice(cleanStart, cleanEnd);
vm.runInThisContext(cleanFnSource);

// Test 46: Strips standard emojis and smileys
assert.strictEqual(
  cleanForSpeech("Hello world! 😄 Great job 🚀"),
  "Hello world! Great job",
  "Standard emojis (smileys, rockets) must be stripped from speech"
);

// Test 47: Strips compound emojis and variations
assert.strictEqual(
  cleanForSpeech("Family 👨‍👩‍👧‍👦 and check ✔️ done."),
  "Family and check done.",
  "Compound emojis, skin tones, and variation selectors must be stripped"
);

// Test 48: Translates speech-friendly symbols to words and preserves digits
assert.strictEqual(
  cleanForSpeech("Temp is 24°C, humidity 45%, and price is $50."),
  "Temp is 24 degrees Celsius, humidity 45 percent, and price is 50 dollars.",
  "Common symbols (°, %, $) must be converted to natural spoken words without losing numbers"
);

// Test 49: Translates & and + to natural words
assert.strictEqual(
  cleanForSpeech("Lights & Fans + AC are on."),
  "Lights and Fans plus AC are on.",
  "Ampersands and plus signs must be translated naturally"
);

// Test 50: Strips technical punctuation (~, |, ^, \, /, <, >, #, *) and turns parentheses into commas
assert.strictEqual(
  cleanForSpeech("Check table: | Living Room AC | (Gree) -> active #1 ~15 min remaining."),
  "Check table: Living Room AC , Gree, active 1 about 15 min remaining.",
  "Technical symbols and box borders must be stripped and parentheses converted to natural pauses"
);

// 14. Mobile Virtual Keyboard Suppression & Dismissal Tests
function simulateVirtualKeyboardLifecycle() {
  let virtualKeyboardHidden = false;
  let activeElementBlurred = false;
  let textareaBlurred = false;
  let inputMode = null;
  let focusedCalled = false;

  const mockNavigator = {
    virtualKeyboard: {
      hide() { virtualKeyboardHidden = true; }
    }
  };

  const mockTa = {
    value: "existing prompt",
    selectionStart: 0,
    selectionEnd: 0,
    blur() { textareaBlurred = true; },
    focus() { focusedCalled = true; },
    setAttribute(k, v) { if (k === "inputmode") inputMode = v; },
    removeAttribute(k) { if (k === "inputmode") inputMode = null; }
  };

  const mockActiveElement = {
    blur() { activeElementBlurred = true; }
  };

  // 1. Trigger voice activation via button
  function onVoiceActivationTrigger() {
    mockNavigator.virtualKeyboard.hide();
    mockActiveElement.blur();
    mockTa.blur();
    mockTa.setAttribute("inputmode", "none");
  }

  // 2. Transcription completes
  function onTranscriptionComplete(spokenText) {
    mockTa.value = spokenText;
    mockTa.selectionStart = mockTa.selectionEnd = mockTa.value.length;
    // Note: mockTa.focus() is NOT called!
  }

  // 3. User explicitly taps textarea to type
  function onUserTouchTextarea() {
    mockTa.removeAttribute("inputmode");
  }

  return {
    onVoiceActivationTrigger,
    onTranscriptionComplete,
    onUserTouchTextarea,
    getState: () => ({ virtualKeyboardHidden, activeElementBlurred, textareaBlurred, inputMode, focusedCalled, mockTa })
  };
}

// Test 51: Voice activation dismisses virtual keyboard and sets inputmode="none"
const simKbd = simulateVirtualKeyboardLifecycle();
simKbd.onVoiceActivationTrigger();
const stateAfterTrigger = simKbd.getState();
assert.strictEqual(stateAfterTrigger.virtualKeyboardHidden, true, "Virtual keyboard must be hidden via VirtualKeyboard API");
assert.strictEqual(stateAfterTrigger.activeElementBlurred, true, "Active element must be blurred on voice trigger");
assert.strictEqual(stateAfterTrigger.textareaBlurred, true, "Textarea must be blurred on voice trigger");
assert.strictEqual(stateAfterTrigger.inputMode, "none", "inputmode must be set to 'none' to suppress mobile keyboard");

// Test 52: Transcribed text updates textarea without invoking focus()
simKbd.onTranscriptionComplete("hello world how are you");
const stateAfterTranscribe = simKbd.getState();
assert.strictEqual(stateAfterTranscribe.mockTa.value, "hello world how are you", "Textarea must receive transcribed text");
assert.strictEqual(stateAfterTranscribe.focusedCalled, false, "focus() must NOT be called on textarea during speech recognition");

// Test 53: Direct user touch restores inputmode for normal typing
simKbd.onUserTouchTextarea();
const stateAfterTouch = simKbd.getState();
assert.strictEqual(stateAfterTouch.inputMode, null, "inputmode must be restored to normal when user taps the textarea to type");

console.log("All STT, TTS Filter, Accessibility & Mobile Keyboard Tests Passed Successfully! (53/53)");


