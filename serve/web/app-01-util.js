// serve/web/app-01-util.js ... app.js - the Strata web app: Code, Monitor, About. No framework, no network beyond this
// server.  It is one program in 11 classic scripts that index.html loads in this order (app-01-util.js first, app.js,
// which starts it, last); they share their globals.  Tests read them together (serve/webapp_source.py).
// The Monitor tab rebuilds PR #22's dashboard idea (code-martin) on the server's own /metrics.
"use strict";

const $ = (id) => document.getElementById(id);
const SPRITE = "web/sprite.svg?v=20261017-stt";
const icon = (name, cls = "st-icon") => {
  if (name === "folder") {
    return `<svg class="${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path opacity="0.25" d="M3 6C3 4.895 3.895 4 5 4H9.172C9.702 4 10.211 4.21 10.586 4.586L12.414 6.414C12.789 6.789 13.298 7 13.828 7H19C20.105 7 21 7.895 21 9V18C21 19.105 20.105 20 19 20H5C3.895 20 3 19.105 3 18V6Z" fill="currentColor"/><path d="M3 6C3 4.895 3.895 4 5 4H9.172C9.702 4 10.211 4.21 10.586 4.586L12.414 6.414C12.789 6.789 13.298 7 13.828 7H19C20.105 7 21 7.895 21 9V18C21 19.105 20.105 20 19 20H5C3.895 20 3 19.105 3 18V6Z"/></svg>`;
  }
  return `<svg class="${cls}" aria-hidden="true"><use href="${SPRITE}#i-${name}"/></svg>`;
};
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const fmt = (n, d = 0) => (n == null || Number.isNaN(n) ? "–" : Number(n).toLocaleString(undefined, {maximumFractionDigits: d, minimumFractionDigits: d}));
const kfmt = (n) => (n == null ? "–" : n >= 1000 ? `${fmt(n / 1000, n >= 10000 ? 0 : 1)}k` : fmt(n));
// a context size: 32768 -> "32K" (powers of two), else like kfmt
const ctxfmt = (n) => (n && n % 1024 === 0 ? `${fmt(n / 1024)}K` : kfmt(n));
const gb = (b, d = 1) => (b == null ? "–" : fmt(b / 1073741824, d));   // memory: binary GB, as Windows shows it

const store = {
  get(k, d) { try { const v = localStorage.getItem("strata." + k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem("strata." + k, JSON.stringify(v)); } catch (e) { /* private mode: in memory only */ } },
};


// ------------------------------------------------------------------ toasts
function dismissAllToasts() {
  const container = $("toasts");
  if (container && container.children.length > 0) {
    container.innerHTML = "";
  }
}
window.addEventListener("pointerdown", (e) => {
  const toastsEl = $("toasts");
  if (toastsEl && toastsEl.children.length > 0) {
    if (e.target && e.target.closest && e.target.closest(".st-toast button")) return;
    const hitToast = Boolean(e.target && e.target.closest && e.target.closest("#toasts"));
    dismissAllToasts();
    if (hitToast && typeof document.elementsFromPoint === "function" && e.clientX != null && e.clientY != null) {
      const underElements = document.elementsFromPoint(e.clientX, e.clientY);
      const interactive = underElements.find(el =>
        el !== toastsEl && !toastsEl.contains(el) && (
          el.tagName === "BUTTON" || el.tagName === "A" || el.tagName === "INPUT" ||
          el.tagName === "TEXTAREA" || el.classList.contains("st-toggle") ||
          el.classList.contains("st-btn") || el.hasAttribute("role") ||
          el.onclick != null
        )
      );
      if (interactive) {
        setTimeout(() => {
          try { interactive.focus(); } catch (_) {}
          try { interactive.click(); } catch (_) {}
        }, 0);
      }
    }
  }
}, { capture: true });

function toast(kind, title, text = "", ms = 3500, action = null) {
  const names = {info: "info", success: "check", warn: "warning", error: "error"};
  const el = document.createElement("div");
  el.className = `st-toast st-toast--${kind}`;
  el.innerHTML = `${icon(names[kind] || "info")}<div><div class="st-toast__title"></div><div class="t-text"></div></div>`;
  el.querySelector(".st-toast__title").textContent = title;
  el.querySelector(".t-text").textContent = text;
  if (action) {
    const b = document.createElement("button");
    b.className = "st-btn st-btn--secondary";
    b.style.height = "32px";
    b.style.marginLeft = "auto";
    b.textContent = action.label;
    b.onclick = (e) => { e.stopPropagation(); action.run(); el.remove(); };
    el.appendChild(b);
  }
  el.onclick = (e) => {
    if (e.target && e.target.tagName === "BUTTON") return;
    el.remove();
  };
  $("toasts").appendChild(el);
  setTimeout(() => { if (el.parentNode) el.remove(); }, ms);
}

async function copyText(text, btn) {
  let done = false;
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text);
      done = true;
    }
  } catch (e) {
    // fall through to legacy fallback
  }
  if (!done) {
    try {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.cssText = "position:fixed;top:0;left:0;opacity:0;pointer-events:none";
      document.body.appendChild(ta);
      ta.select();
      done = document.execCommand("copy");
      ta.remove();
    } catch (_) {
      done = false;
    }
  }
  if (done) {
    if (btn) {
      const use = btn.querySelector("use");
      if (use) {
        use.setAttribute("href", `${SPRITE}#i-check`);
        setTimeout(() => use.setAttribute("href", `${SPRITE}#i-copy`), 1500);
      } else {
        const origText = btn.textContent;
        btn.textContent = "Copied!";
        setTimeout(() => { btn.textContent = origText; }, 1500);
      }
    }
    toast("success", "Copied", "", 1800);
  } else {
    toast("warn", "Couldn’t copy", "Select the text and copy it manually.", 4000);
  }
  return done;
}

