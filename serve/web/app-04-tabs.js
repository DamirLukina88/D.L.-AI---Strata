// serve/web/app-04-tabs.js - part of the web app (see app-01-util.js): theme and tabs.
// A classic script, loaded in order by index.html; it shares its globals with the others.
"use strict";

// ------------------------------------------------------------------ theme and tabs
// the system's theme until the user picks one (only a click is saved)
function setTheme(t, save) {
  document.documentElement.dataset.theme = t;
  if (save) try { localStorage.setItem("strata.theme", t); } catch (e) { /* ignore */ }
  $("theme-icon").setAttribute("href", `${SPRITE}#i-${t === "dark" ? "sun" : "moon"}`);
  $("dark-toggle").setAttribute("aria-checked", String(t === "dark"));
}
const flipTheme = () => setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark", true);
$("theme-btn").onclick = flipTheme;
$("dark-toggle").onclick = flipTheme;
setTheme(document.documentElement.dataset.theme || "dark", false);
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", (e) => {
  let saved = null;
  try { saved = localStorage.getItem("strata.theme"); } catch (err) { /* ignore */ }
  if (saved) setTheme(saved, false);
});

let tab = "code";
// 1200 px and wider: Code on the left and Monitor (or About) on the right, with a draggable divider between them
const splitQuery = matchMedia("(min-width: 1200px)");
let split = splitQuery.matches;
let side = "monitor";                                      // the right pane in the side-by-side view
function shown(v) { return split ? v === "code" || v === side : v === tab; }
function showTab(name) {
  if (typeof STTController !== "undefined") STTController.cancelAutoSendTimer();
  tab = ["code", "monitor", "about"].includes(name) ? name : "code";
  if (split && tab !== "code") side = tab;
  document.body.classList.toggle("is-split", split);
  if ($("split-handle")) $("split-handle").hidden = !split;
  for (const b of document.querySelectorAll(".st-tab")) {
    b.setAttribute("aria-selected", String(split ? b.dataset.tab === side : b.dataset.tab === tab));
  }
  for (const v of ["code", "monitor", "about"]) {
    if ($(`view-${v}`)) $(`view-${v}`).hidden = !shown(v);
  }
  const currentHash = location.hash.slice(1);
  if (tab === "code" && currentHash) {
    history.replaceState(null, "", location.pathname);
  } else if (tab !== "code" && currentHash !== tab) {
    history.replaceState(null, "", `#${tab}`);
  }
  if (shown("code")) openCodeSession(); else codeDisconnect();
  if (shown("monitor")) loadMcp();
  if (shown("about")) loadConfig();
  if (lastMetrics) render(lastMetrics);
}
function checkSplit() { if (splitQuery.matches !== split) { split = splitQuery.matches; showTab(tab); } }
splitQuery.addEventListener("change", checkSplit);
window.addEventListener("resize", checkSplit);            // some browsers (and devtools emulation) skip the change event

(function splitHandle() {
  const handle = $("split-handle");
  if (!handle) return;
  const set = (pct, save) => {
    pct = Math.min(75, Math.max(25, pct));
    document.documentElement.style.setProperty("--split", `${pct}%`);
    handle.setAttribute("aria-valuenow", String(Math.round(pct)));
    if (save) store.set("splitPct", pct);
  };
  set(Number(store.get("splitPct", 50)) || 50, false);
  handle.setAttribute("aria-valuemin", "25");
  handle.setAttribute("aria-valuemax", "75");
  const at = (x) => { const r = document.querySelector("main").getBoundingClientRect(); return ((x - r.left) / r.width) * 100; };
  handle.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    e.preventDefault();
    handle.setPointerCapture(e.pointerId);
    handle.classList.add("is-dragging");
    document.body.classList.add("is-resizing");
  });
  handle.addEventListener("pointermove", (e) => { if (handle.hasPointerCapture(e.pointerId)) set(at(e.clientX), false); });
  const end = (e) => {
    if (!handle.classList.contains("is-dragging")) return;
    handle.classList.remove("is-dragging");
    document.body.classList.remove("is-resizing");
    if (e.type === "pointerup") set(at(e.clientX), true);
    else store.set("splitPct", parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--split")) || 50);
  };
  handle.addEventListener("pointerup", end);
  handle.addEventListener("pointercancel", end);
  handle.addEventListener("dblclick", () => set(50, true));
  handle.addEventListener("keydown", (e) => {
    const now = Number(handle.getAttribute("aria-valuenow")) || 50;
    if (e.key === "ArrowLeft" || e.key === "ArrowRight") { e.preventDefault(); set(now + (e.key === "ArrowLeft" ? -2 : 2), true); }
    else if (e.key === "Home" || e.key === "Enter") { e.preventDefault(); set(50, true); }
  });
})();
for (const b of document.querySelectorAll(".st-tab")) b.onclick = () => showTab(b.dataset.tab);
window.addEventListener("hashchange", () => showTab(location.hash.slice(1)));

