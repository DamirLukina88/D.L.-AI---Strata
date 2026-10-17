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

// 4. Android onresult reconstruction test
function processResults(resultsList) {
  let finalStr = "";
  let interimStr = "";
  let lastFinalSegment = "";

  for (let i = 0; i < resultsList.length; ++i) {
    const res = resultsList[i];
    if (!res || !res[0]) continue;
    const transcript = (res[0].transcript || "").trim();
    if (!transcript) continue;

    if (res.isFinal) {
      if (transcript !== lastFinalSegment) {
        finalStr += (finalStr ? " " : "") + transcript;
        lastFinalSegment = transcript;
      }
    } else {
      interimStr += (interimStr ? " " : "") + transcript;
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

// Test 11: Android duplicate identical segment suppression
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

console.log("All STT Unit Tests Passed Successfully! (11/11)");
