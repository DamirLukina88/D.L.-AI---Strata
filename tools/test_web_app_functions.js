// tools/test_web_app_functions.js - the web app's own pure functions, cut out of serve/web/app.js and run in Node
// (the other JS tests copy the logic into the test, so they can't catch a change in the page itself).
// Run: node tools/test_web_app_functions.js
"use strict";

const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const SRC = require("./web_app_source").appJsText();     // the web app is several scripts (serve/web/app-*.js)

// a top-level `function name(...) { ... }` from app.js, by matching braces (strings and regexes in these functions
// keep their braces balanced)
function cut(name) {
  const start = SRC.indexOf(`\nfunction ${name}(`);
  assert.ok(start >= 0, `app.js has no function ${name}`);
  let i = SRC.indexOf("{", start), depth = 0;
  for (; i < SRC.length; i++) {
    if (SRC[i] === "{") depth++;
    else if (SRC[i] === "}" && --depth === 0) break;
  }
  return SRC.slice(start + 1, i + 1);
}
const escLine = SRC.split("\n").find((l) => l.startsWith("const esc = "));
const ctx = vm.createContext({});
vm.runInContext([escLine, ...["cleanForSpeech", "chunkText", "mergeSpeechTranscripts", "inline", "blocks", "markdown", "buildWorkspaceTree",
  "folderFilePaths"].map(cut), "this.api = {esc, cleanForSpeech, chunkText, mergeSpeechTranscripts, markdown, " +
  "buildWorkspaceTree, folderFilePaths};"].join("\n"), ctx);
const {cleanForSpeech, chunkText, mergeSpeechTranscripts, markdown, buildWorkspaceTree, folderFilePaths} = ctx.api;

let n = 0;
const test = (name, fn) => { fn(); n++; console.log(`  ok ${name}`); };
console.log("Web app functions (serve/web/app.js):");

test("cleanForSpeech drops code blocks and keeps the words", () => {
  const out = cleanForSpeech("Here is the fix:\n```js\nconst a = 1;\n```\nIt works now.", "skip");
  assert.ok(!out.includes("const a"), out);
  assert.ok(out.includes("Here is the fix") && out.includes("It works now"), out);
});

test("cleanForSpeech reads a link's label, not its URL", () => {
  const out = cleanForSpeech("See [the docs](https://example.com/docs) for more.");
  assert.ok(out.includes("the docs") && !out.includes("https://"), out);
});

test("chunkText keeps every word and respects the length", () => {
  const text = "One sentence here. ".repeat(40).trim();
  const chunks = chunkText(text, 120);
  assert.ok(chunks.length > 1);
  assert.ok(chunks.every((c) => c.length <= 120), chunks.map((c) => c.length).join(","));
  assert.strictEqual(chunks.join(" ").replace(/\s+/g, " ").trim(), text.replace(/\s+/g, " "));
});

test("mergeSpeechTranscripts joins overlaps without repeating", () => {
  assert.strictEqual(mergeSpeechTranscripts("turn on the", "on the lights"), "turn on the lights");
  assert.strictEqual(mergeSpeechTranscripts("hello", "hello world"), "hello world");      // Android's cumulative text
  assert.strictEqual(mergeSpeechTranscripts("hello world", "world"), "hello world");      // a repeated tail
  assert.strictEqual(mergeSpeechTranscripts("", "hi"), "hi");
});

test("markdown escapes HTML in the text", () => {
  const html = markdown("**bold** and <script>alert(1)</script>");
  assert.ok(html.includes("<strong>bold</strong>") || html.includes("<b>bold</b>"), html);
  assert.ok(!html.includes("<script>"), html);
});

test("workspace tree: a folder tick reaches every file inside, subfolders too", () => {
  const files = [
    {path: "a.txt", name: "a.txt", size: 1, mtime: 0},
    {path: "pics/b.jpg", name: "b.jpg", size: 2, mtime: 0},
    {path: "pics/2026/c.jpg", name: "c.jpg", size: 3, mtime: 0},
    {path: "pics", name: "pics", is_dir: true, size: 0, mtime: 0},
  ];
  const tree = buildWorkspaceTree(files, "");
  // arrays made inside the vm context have its Array prototype: copy them out before comparing
  assert.deepStrictEqual(Array.from(tree.files, (f) => f.path), ["a.txt"]);
  const pics = tree.folders.get("pics");
  assert.ok(pics, [...tree.folders.keys()].join(","));
  assert.deepStrictEqual(Array.from(folderFilePaths(pics)).sort(), ["pics/2026/c.jpg", "pics/b.jpg"]);
});

console.log(`All ${n} web app function tests passed.`);

// "Loading model…" got stuck: a failed POST /load left modelLoading set, so tapping Ray never woke the model again;
// a slash command run while it slept set it too and nothing cleared it
(async () => {
  const calls = [];
  const wctx = vm.createContext({toast() {}, setPill() {}, headers() { return {}; },
                                 fetch: async (url) => { calls.push(url); return {ok: false, status: 401}; }});
  const at = SRC.indexOf("\nasync function wakeModelFromSleep(");
  assert.ok(at >= 0, "app.js has no async function wakeModelFromSleep");
  let i = SRC.indexOf("{", at), depth = 0;
  for (; i < SRC.length; i++) {
    if (SRC[i] === "{") depth++;
    else if (SRC[i] === "}" && --depth === 0) break;
  }
  vm.runInContext("var modelUnloaded = true, modelLoading = false;\n" + SRC.slice(at + 1, i + 1) +
                  "\nthis.wake = wakeModelFromSleep; this.loading = () => modelLoading;", wctx);
  await wctx.wake();
  assert.strictEqual(wctx.loading(), false, "a refused /load must not leave modelLoading set");
  await wctx.wake();
  assert.strictEqual(calls.length, 2, "a second tap must try /load again");
  const idle = SRC.slice(SRC.indexOf("\nfunction codeSetState("));
  assert.ok(/\} else \{[\s\S]{0,400}?if \(modelUnloaded\) modelLoading = false;/.test(idle.slice(0, 6000)),
            "codeSetState's idle branch clears modelLoading while the model sleeps");
  console.log("  ok wakeModelFromSleep and codeSetState never leave \"Loading model…\" stuck");
})().catch((e) => { console.error(e); process.exitCode = 1; });

// sensor polling, dialogs and code-block copy (audit 2026-11-18)
(async () => {
  const cutAsync = (name) => {
    const at = SRC.indexOf(`\nasync function ${name}(`);
    assert.ok(at >= 0, `no async function ${name}`);
    let i = SRC.indexOf("{", at), depth = 0;
    for (; i < SRC.length; i++) {
      if (SRC[i] === "{") depth++;
      else if (SRC[i] === "}" && --depth === 0) break;
    }
    return SRC.slice(at + 1, i + 1);
  };
  let release, calls = 0;
  const sctx = vm.createContext({window: {}, headers() { return {}; }, applySensorData() {},
    fetch: () => { calls++; return new Promise((res) => { release = () => res({ok: true, json: async () => ({})}); }); }});
  vm.runInContext("var sensorFetchInFlight = false;\n" + cutAsync("fetchSensorData") + "\nthis.f = fetchSensorData;", sctx);
  const first = sctx.f();
  sctx.f();
  sctx.f();
  assert.strictEqual(calls, 1, "a sensor poll waits for the one in flight");
  release();
  await first;
  sctx.f();
  assert.strictEqual(calls, 2, "the next poll runs once the last one ended");
  release();
  for (const dlg of ["wsDialog", "sensorsDlg", "sensorInfoModal"]) {
    const at = SRC.indexOf(`${dlg}.addEventListener("click", (e) => {`);
    assert.ok(at >= 0, dlg);
    assert.ok(SRC.slice(at, at + 400).includes(`if (e.target !== ${dlg}) return;`),
              `${dlg} closes only on a click on its backdrop`);
  }
  const cp = SRC.indexOf('const cp = e.target.closest("[data-code-copy]");');
  assert.ok(SRC.slice(cp, cp + 500).includes('cp.closest(".st-code")'), "a code block's copy button copies the block");
  console.log("  ok sensor polling, dialog backdrop clicks and code-block copy");
})().catch((e) => { console.error(e); process.exitCode = 1; });
