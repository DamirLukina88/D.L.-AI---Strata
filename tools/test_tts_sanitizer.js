// tools/test_tts_sanitizer.js - Unit tests for TTS text sanitization and chunking algorithms.
"use strict";

const assert = require("assert");

function cleanForSpeech(rawText, codeMode = "skip") {
  if (!rawText) return "";
  let text = String(rawText);

  // 1. Remove thinking / reasoning blocks (<think>...</think>)
  text = text.replace(/<think>[\s\S]*?<\/think>/gi, "");
  // Remove unclosed <think> tag if present during stream
  text = text.replace(/<think>[\s\S]*$/gi, "");

  // 2. Handle fenced code blocks (```lang ... ```)
  text = text.replace(/(?:^|\n)```([^\n`]*)\n([\s\S]*?)(?:^|\n)```[ \t]*(?:\n|$)/g, (match, lang, code) => {
    if (codeMode === "skip") {
      return " [Code block omitted.] ";
    } else if (codeMode === "summary") {
      const lineCount = code.trim().split("\n").filter(l => l.trim().length > 0).length;
      const lName = (lang || "").trim() || "Code";
      return ` [${lName} code block, ${lineCount} lines.] `;
    } else {
      return ` [Code: ${code.trim()}] `;
    }
  });

  // Handle any remaining unclosed code blocks
  text = text.replace(/(?:^|\n)```[^\n`]*\n[\s\S]*$/g, " [Code block omitted.] ");

  // 3. Strip Markdown Headings (# Header)
  text = text.replace(/^#{1,6}\s+/gm, "");

  // 4. Strip Bold and Italics (**bold**, *italic*, __bold__, _italic_)
  text = text.replace(/[*_]{1,3}([^*_]+)[*_]{1,3}/g, "$1");

  // 5. Strip Blockquotes (> quote)
  text = text.replace(/^>\s*/gm, "");

  // 6. Strip List bullets and numbers (- item, * item, 1. item)
  text = text.replace(/^[\s]*[-*+]\s+/gm, "");
  text = text.replace(/^[\s]*\d+\.\s+/gm, "");

  // 7. Strip inline code (`code`)
  text = text.replace(/`([^`]+)`/g, "$1");

  // 8. Convert markdown links [Label](url) to just Label
  text = text.replace(/\[([^\]]+)\]\([^)]+\)/g, "$1");

  // 9. Strip bare URLs
  text = text.replace(/https?:\/\/[^\s]+/g, "link");

  // 10. Strip horizontal rules (---, ***, ___)
  text = text.replace(/^[-*_]{3,}\s*$/gm, "");

  // 11. Strip HTML tags (only tags starting with a-z or /)
  text = text.replace(/<[a-zA-Z\/][^>]*>/g, " ");

  // 12. Normalize LaTeX / Math formulas ($x^2$, $$formula$$)
  text = text.replace(/\$\$([^$]+)\$\$/g, "$1");
  text = text.replace(/\$([^$]+)\$/g, "$1");

  // 13. Normalize em-dashes (—), en-dashes (–), horizontal bars (―), figure dashes (‒) to natural pause
  text = text.replace(/\s*[\u2012\u2013\u2014\u2015\u2212]\s*/g, ", ");

  // 14. Normalize smart quotes, apostrophes, ellipsis, zero-width characters
  text = text.replace(/[\u2018\u2019]/g, "'");
  text = text.replace(/[\u201C\u201D]/g, '"');
  text = text.replace(/\u2026/g, "...");
  text = text.replace(/[\u200B-\u200D\uFEFF\u00AD]/g, "");

  // 15. Collapse multiple whitespace, preserve natural sentence spacing
  text = text.replace(/[ \t]+/g, " ");
  text = text.replace(/\n\s*\n/g, "\n");
  text = text.trim();

  return text;
}

function chunkText(text, maxLen = 240) {
  if (!text) return [];
  const clean = text.trim();
  if (clean.length <= maxLen) return [clean];

  // Protect common abbreviations, decimals, and versions from improper splitting
  const safe = clean.replace(/\b(e\.g\.|i\.e\.|vs\.|dr\.|mr\.|mrs\.|ms\.)/gi, (m) => m.replace(/\./g, "\u2024"))
                    .replace(/(\d+)\.(\d+)/g, "$1\u2024$2");

  const chunks = [];
  const rawSentences = safe.split(/(?<=[.!?;\n])\s+/);

  for (const raw of rawSentences) {
    const s = raw.replace(/\u2024/g, ".").trim();
    if (!s) continue;

    if (s.length <= maxLen) {
      // Check if we can merge with the previous chunk if combined length <= maxLen
      if (chunks.length > 0 && chunks[chunks.length - 1].length + 1 + s.length <= maxLen) {
        chunks[chunks.length - 1] += " " + s;
      } else {
        chunks.push(s);
      }
    } else {
      // Sentence exceeds maxLen: split by clause punctuation (commas, dashes, colons)
      const clauses = s.split(/(?<=[,:\-\–—])\s+/);
      let cur = "";

      for (const clause of clauses) {
        if (!clause) continue;
        if ((cur + " " + clause).trim().length <= maxLen) {
          cur = (cur ? cur + " " + clause : clause).trim();
        } else {
          if (cur) chunks.push(cur);
          // If a single clause itself is still longer than maxLen, split by words
          if (clause.length > maxLen) {
            const words = clause.split(/\s+/);
            let wCur = "";
            for (const w of words) {
              if ((wCur + " " + w).trim().length <= maxLen) {
                wCur = (wCur ? wCur + " " + w : w).trim();
              } else {
                if (wCur) chunks.push(wCur);
                wCur = w;
              }
            }
            cur = wCur;
          } else {
            cur = clause;
          }
        }
      }
      if (cur) chunks.push(cur);
    }
  }

  return chunks.filter(c => c.length > 0);
}

// -------------------------------------------------------------
// Test Suite Execution
// -------------------------------------------------------------
console.log("Running TTS Text Sanitizer & Chunker Test Suite...");

// Test 1: Thinking block removal
{
  const input = "<think>\nLet's evaluate the hardware options.\nRX 7600 XT is gfx1102.\n</think>\nHere is the answer.";
  const cleaned = cleanForSpeech(input);
  assert.strictEqual(cleaned, "Here is the answer.");
  console.log("✓ Test 1 Passed: <think> tags completely eliminated");
}

// Test 2: Code block handling - 'skip'
{
  const input = "Before code.\n```python\ndef test():\n    return 42\n```\nAfter code.";
  const cleaned = cleanForSpeech(input, "skip");
  assert.strictEqual(cleaned, "Before code. [Code block omitted.] After code.");
  console.log("✓ Test 2 Passed: Code block 'skip' replacement");
}

// Test 3: Code block handling - 'summary'
{
  const input = "Check this:\n```javascript\nconst a = 1;\nconst b = 2;\nconsole.log(a + b);\n```\nDone.";
  const cleaned = cleanForSpeech(input, "summary");
  assert.strictEqual(cleaned, "Check this: [javascript code block, 3 lines.] Done.");
  console.log("✓ Test 3 Passed: Code block 'summary' mode with line count");
}

// Test 4: Markdown formatting stripped
{
  const input = "### Heading 3\nThis is **bold** and *italic* with `inline_code()` and [Strata Docs](https://strata.ai/docs).";
  const cleaned = cleanForSpeech(input);
  assert.strictEqual(cleaned, "Heading 3\nThis is bold and italic with inline_code() and Strata Docs.");
  console.log("✓ Test 4 Passed: Markdown syntax stripped cleanly");
}

// Test 5: Long text chunking within maxLen constraint
{
  const longText = "Strata runs the Qwen3.8-Flash-Next mixture-of-experts model on a normal PC with one graphics card plus system RAM. " +
    "It features a custom C++ and HIP execution engine for AMD RDNA3 architecture. " +
    "The prefill throughput reaches over 326 tokens per second at 32K context window. " +
    "Furthermore, the FP32 SIMT QSA tiled scorer provides high performance expert routing across 256 routed experts with zero divergence. " +
    "All components have been verified locally on CachyOS Linux with ROCm 7.2.4.";

  const chunks = chunkText(longText, 180);
  assert.ok(chunks.length >= 2, "Expected multiple chunks");
  for (let i = 0; i < chunks.length; i++) {
    assert.ok(chunks[i].length <= 180, `Chunk ${i} exceeds 180 chars: ${chunks[i].length} chars`);
    assert.ok(!chunks[i].startsWith(" "), `Chunk ${i} has leading whitespace`);
  }
  console.log(`✓ Test 5 Passed: Long text (${longText.length} chars) cleanly chunked into ${chunks.length} chunks (all <= 180 chars)`);
}

// Test 6: Extreme clause without punctuation
{
  const runon = "word ".repeat(50); // 250 characters without punctuation
  const chunks = chunkText(runon, 180);
  for (const c of chunks) {
    assert.ok(c.length <= 180, `Word split chunk exceeded maxLen: ${c.length}`);
  }
  console.log(`✓ Test 6 Passed: Unpunctuated run-on clause cleanly word-split into ${chunks.length} chunks`);
}

// Test 7: Em-dash and unicode dash normalization (prevents Android TTS cutoff)
{
  const input = "The city didn't erase old families—it folded new ones into its fabric.";
  const cleaned = cleanForSpeech(input);
  assert.strictEqual(cleaned, "The city didn't erase old families, it folded new ones into its fabric.");
  console.log("✓ Test 7 Passed: Em-dash cleanly normalized to pause comma");
}

// Test 8: Smart quotes, en-dashes, and ellipsis normalization
{
  const input = "“Hello world”… said the author – with pride.";
  const cleaned = cleanForSpeech(input);
  assert.strictEqual(cleaned, '"Hello world"... said the author, with pride.');
  console.log("✓ Test 8 Passed: Smart quotes, en-dash, and ellipsis normalized");
}

// Test 9: Decimal numbers and abbreviations preserved from premature splitting
{
  const input = "The server is running on 23.7 GB of RAM, version 1.2 of the protocol, e.g. on port 8080. Everything is operational.";
  const chunks = chunkText(input, 240);
  assert.strictEqual(chunks.length, 1);
  assert.ok(chunks[0].includes("23.7 GB"));
  assert.ok(chunks[0].includes("e.g. on port 8080"));
  console.log("✓ Test 9 Passed: Decimals and abbreviations kept intact in natural chunk");
}

// Test 10: Math inequalities preserved while HTML tags are cleanly stripped
{
  const input = "<div>Notice: if count < 10 and max > 50, then check <path/to/file>.</div>";
  const cleaned = cleanForSpeech(input);
  assert.ok(cleaned.includes("count < 10 and max > 50"), "Math inequality should not be stripped as HTML tag");
  assert.ok(!cleaned.includes("<div>"), "HTML opening tag stripped");
  assert.ok(!cleaned.includes("</div>"), "HTML closing tag stripped");
  console.log("✓ Test 10 Passed: Math inequalities preserved while HTML tags stripped");
}

console.log("\n=======================================================");
console.log("ALL 10 TTS SANITIZER & CHUNKER UNIT TESTS PASSED (100%)!");
console.log("=======================================================\n");
