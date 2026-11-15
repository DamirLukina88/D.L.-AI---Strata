// serve/web/app.js - part of the web app (see app-01-util.js): start.
// A classic script, loaded in order by index.html; it shares its globals with the others.
"use strict";

// ------------------------------------------------------------------ start
function autosize() { const inp = (typeof $ === "function" ? $("input") : null) || (typeof document !== "undefined" ? (document.getElementById("code-mobile-input") || document.getElementById("input")) : null); if (inp && inp.scrollHeight) inp.style.height = inp.scrollHeight + "px"; }
async function start() {
  if (typeof checkRayAndroidCompanion === "function") checkRayAndroidCompanion();
  if (typeof TTSController !== "undefined") TTSController.init();
  if (typeof STTController !== "undefined") STTController.init();
  const startQuestion = new URLSearchParams(location.search).get("q");
  if (startQuestion) {
    history.replaceState(null, "", location.pathname + location.hash);
    const inp = (typeof $ === "function" ? $("input") : null) || (typeof document !== "undefined" ? (document.getElementById("code-mobile-input") || document.getElementById("input")) : null);
    if (inp) {
      inp.value = startQuestion;
      autosize();
    }
  }
  if (typeof loadHealth === "function") {
    const p = loadHealth().then(typeof loadMcp === "function" ? loadMcp : () => {});
    if (typeof loadAvailableModels === "function") p.then(loadAvailableModels);
  }
  if (typeof showTab === "function") showTab(location.hash.slice(1) || "code");
  if (startQuestion) {
    const inp = (typeof $ === "function" ? $("input") : null) || (typeof document !== "undefined" ? (document.getElementById("code-mobile-input") || document.getElementById("input")) : null);
    if (inp) inp.focus();
  }
  if (typeof poll === "function") poll();
}
start();

// composer onsubmit handler
function sendComposerAction(e) { if (e && e.preventDefault) e.preventDefault(); send(); }
async function send(payload) { if (typeof codeSend === "function") codeSend(payload); }
