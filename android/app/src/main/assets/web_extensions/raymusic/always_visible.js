// Ray's lock-screen player: the page always counts as visible.  YouTube Music without Premium pauses a song when
// its page is hidden, and the screen going off hid it (measured 2026-11-09 19:18: power button, song stopped 1 s
// later; Play from the headset resumed it).  The old WebView player patched the same thing.  Runs at document_start,
// before the page's own scripts, on music.youtube.com only.
(function () {
  "use strict";
  const page = window.wrappedJSObject;
  const doc = document.wrappedJSObject;
  try {
    const visible = exportFunction(function () { return "visible"; }, window);
    const notHidden = exportFunction(function () { return false; }, window);
    Object.defineProperty(doc, "visibilityState", { get: visible, configurable: true });
    Object.defineProperty(doc, "hidden", { get: notHidden, configurable: true });
    Object.defineProperty(doc, "webkitVisibilityState", { get: visible, configurable: true });
    Object.defineProperty(doc, "webkitHidden", { get: notHidden, configurable: true });
    if (doc.hasFocus) Object.defineProperty(doc, "hasFocus", { value: exportFunction(function () { return true; }, window), configurable: true });
  } catch (e) {
    console.log("[ray-audio] visibility patch failed: " + e);
  }
  // the page never hears that it was hidden (a capturing listener on window runs before the page's own)
  const swallow = function (e) {
    e.stopImmediatePropagation();
    console.log("[ray-audio] kept the page visible (" + e.type + ")");
  };
  window.addEventListener("visibilitychange", swallow, true);
  window.addEventListener("webkitvisibilitychange", swallow, true);
  window.addEventListener("pagehide", function (e) { if (e.persisted === false) return; }, true);
  window.addEventListener("blur", function (e) { if (e.target === window) e.stopImmediatePropagation(); }, true);
  void page;
})();
