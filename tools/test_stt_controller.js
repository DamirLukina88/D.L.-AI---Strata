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

console.log("All STT Unit Tests Passed Successfully! (22/22)");



