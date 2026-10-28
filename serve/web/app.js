// serve/web/app.js - the Strata web app: Chat, Monitor, About. No framework, no network beyond this server.
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

const isMobile = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent) || (typeof window !== "undefined" && window.matchMedia && window.matchMedia("(pointer: coarse)").matches);

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

/** Robust decimal parser supporting commas, dots, and partial editing (#3736). */
function parseDecimal(text) {
  const t = String(text ?? "").trim().replace(",", ".");
  if (!/^-?(\d+\.?\d*|\.\d+)$/.test(t) || t.endsWith(".")) return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
}
function partialDecimal(text) {
  return /^-?\d*[.,]?\d*$/.test(String(text ?? "").trim());
}

// ------------------------------------------------------------------ Text-to-Speech (TTS) Engine
function cleanForSpeech(rawText, codeMode = "skip") {
  if (!rawText) return "";
  let text = String(rawText);

  // 1. Remove thinking / reasoning blocks (<think>...</think>)
  text = text.replace(/<think>[\s\S]*?<\/think>/gi, "");
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

  // 12. Currency, percentages, temperatures, and numbers with units (before LaTeX/math stripping)
  text = text.replace(/\$(\d+(?:\.\d+)?)/g, (_, num) => `${num} dollars`);
  text = text.replace(/(\d+)\s*%/g, (_, num) => `${num} percent`);
  text = text.replace(/%/g, " percent ");
  text = text.replace(/(\d+)\s*°\s*C\b/gi, (_, num) => `${num} degrees Celsius`);
  text = text.replace(/(\d+)\s*°\s*F\b/gi, (_, num) => `${num} degrees Fahrenheit`);
  text = text.replace(/°/g, " degrees ");
  text = text.replace(/~(\d+)/g, (_, num) => `about ${num}`);

  // 13. Translate speech-friendly symbols into natural words
  text = text.replace(/&/g, " and ");
  text = text.replace(/@([a-zA-Z0-9_]+)/g, (_, handle) => `at ${handle}`);
  text = text.replace(/@/g, " at ");
  text = text.replace(/->|→|=>|⇒/g, ", ");
  text = text.replace(/\s*\+\s*/g, " plus ");
  text = text.replace(/\s*=\s*/g, " equals ");

  // 14. Normalize LaTeX / Math formulas ($x^2$, $$formula$$)
  text = text.replace(/\$\$([^$]+)\$\$/g, "$1");
  text = text.replace(/\$([^$]+)\$/g, "$1");

  // 15. Strip all Unicode Emojis, smileys, pictograms, modifiers, and joiners
  text = text.replace(/[\p{Extended_Pictographic}\p{Emoji_Modifier}\uFE0E\uFE0F\u200D]+/gu, "");

  // 16. Strip decorative, box-drawing, bullet, shape, and arrow symbols
  text = text.replace(/[\u2190-\u21FF\u27F0-\u27FF\u2900-\u297F\u2500-\u257F\u2580-\u259F\u25A0-\u25FF\u2600-\u26FF\u2B00-\u2BFF]/g, " ");
  text = text.replace(/[•●■◆▪▫◦★☆✓✔✕✖✗]/g, " ");

  // 17. Strip technical punctuation and symbols that TTS engines pronounce awkwardly
  text = text.replace(/[~|^\\<>/#*_§©®™]/g, " ");

  // 18. Replace parentheses with gentle commas so speech intones naturally without pronouncing "parenthesis"
  text = text.replace(/\(([^)]+)\)/g, ", $1, ");

  // 19. Normalize em-dashes (—), en-dashes (–), horizontal bars (―), figure dashes (‒) to natural pause
  // Android TTS tokenizers crash or abort speech when encountering raw em-dashes without spaces
  text = text.replace(/\s*[\u2012\u2013\u2014\u2015\u2212]\s*/g, ", ");

  // 20. Normalize smart quotes, apostrophes, ellipsis, zero-width characters
  text = text.replace(/[\u2018\u2019]/g, "'");
  text = text.replace(/[\u201C\u201D]/g, '"');
  text = text.replace(/\u2026/g, "...");
  text = text.replace(/[\u200B-\u200D\uFEFF\u00AD]/g, "");

  // 21. Collapse multiple punctuation marks and whitespace
  text = text.replace(/,\s*,+/g, ",");
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
      if (chunks.length > 0 && chunks[chunks.length - 1].length + 1 + s.length <= maxLen) {
        chunks[chunks.length - 1] += " " + s;
      } else {
        chunks.push(s);
      }
    } else {
      const clauses = s.split(/(?<=[,:\-\–—])\s+/);
      let cur = "";

      for (const clause of clauses) {
        if (!clause) continue;
        if ((cur + " " + clause).trim().length <= maxLen) {
          cur = (cur ? cur + " " + clause : clause).trim();
        } else {
          if (cur) chunks.push(cur);
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

// female voices by name, for browsers without Piper: Piper's own, Edge/Windows, Chrome desktop, Apple, Android
const RAY_FEMALE_VOICE = new RegExp("female|hfc_female|amy|kristin|lessac|ljspeech|kathleen|aria|jenny|ava\\b|emma|" +
  "michelle|ana\\b|sonia|libby|maisie|natasha|clara|zira|hazel|susan|samantha|karen|moira|tessa|serena|victoria|allison|" +
  "google us english|google uk english female|-x-(?:sfg|tpc|iob|iog)", "i");
const TTSController = {
  queue: [],
  currentIndex: 0,
  speaking: false,
  paused: false,
  activeBtn: null,
  activeMsg: null,
  watchdogTimer: null,
  wakeLock: null,
  audioCtx: null,
  _silentSource: null,
  currentUtterance: null, // V8 Garbage Collection Anchor

  getVoice() {
    if (!window.speechSynthesis) return null;
    const voices = window.speechSynthesis.getVoices();
    if (!voices || voices.length === 0) return null;

    const uri = store.get("tts_voice", "");
    if (uri) {
      const match = voices.find((v) => v.voiceURI === uri || v.name === uri);
      // Only keep saved match if it's not a legacy eSpeak voice when Piper is available
      if (match && (!/espeak/i.test(match.name || match.voiceURI) || !voices.some((v) => /piper|lessac|ryan/i.test(v.name || v.voiceURI)))) {
        return match;
      }
    }

    // 1. Highest priority: Ray's voice (Piper HFC female), then other Piper neural voices (lessac / ryan)
    const piper = voices.find((v) => /hfc_female/i.test(v.name || v.voiceURI)) ||
                  voices.find((v) => /piper|lessac|ryan/i.test(v.name || v.voiceURI));
    if (piper) return piper;

    // Ray is female: without Piper (a phone, Edge, macOS) each step below takes a female voice of its kind first, since
    // the first "Natural" voice is often male (Edge lists "Microsoft Andrew Online (Natural)" early).  Android Chrome
    // names voices by language only ("English United States", lang en_US): there the local US voice, female by
    // default, comes before the first English voice in the list (which was male, 2026-10-23)
    const us = (v) => /^en[-_]us$/i.test(v.lang || "");
    const female = (list) => list.find((v) => RAY_FEMALE_VOICE.test(v.name || v.voiceURI)) ||
                             list.find((v) => us(v) && v.localService) || list.find(us) || list[0];

    // 2. High priority: Native neural / natural voices (Edge Natural / Chrome OS Neural / Apple Siri)
    const natural = female(voices.filter((v) => /natural|neural|online/i.test(v.name || v.voiceURI)));
    if (natural) return natural;

    // 3. English non-eSpeak local voice
    const enNonEspeak = female(voices.filter((v) => /^en/i.test(v.lang) && !/espeak/i.test(v.name || v.voiceURI)));
    if (enNonEspeak) return enNonEspeak;

    // 4. Any non-eSpeak local voice
    const anyNonEspeak = female(voices.filter((v) => !/espeak/i.test(v.name || v.voiceURI)));
    if (anyNonEspeak) return anyNonEspeak;

    // 5. System default or first available
    return voices.find((v) => v.default) || voices.find((v) => v.localService) || voices[0] || null;
  },

  getRate() { return +store.get("tts_rate", 1.0); },
  getPitch() { return +store.get("tts_pitch", 1.0); },
  getCodeMode() { return store.get("tts_code_mode", "skip"); },
  // on unless turned off: a spoken prompt is answered aloud (typed ones never are)
  isAutoSpeak() { return store.get("tts_auto_speak", true) !== false; },
  // on unless turned off in About: Ray's face while reading aloud, and the thinking circle (web/rayface.js)
  isOrbOn() { return store.get("tts_orb", true) !== false; },
  orb() { return typeof RayFace !== "undefined" && this.isOrbOn() && !(this.activeBtn && this.activeBtn.id === "tts-test-btn"); },
  // Ray's Piper voice made by the server (POST v1/audio/speech): on unless turned off, when the server has it.  The
  // audio plays through Web Audio, so the face's waveform follows the voice; a failure falls back to the browser voice.
  serverTTS: null,
  isServerVoiceOn() { return store.get("tts_server", true) !== false; },
  useServer() { return this.isServerVoiceOn() && !!(this.serverTTS && this.serverTTS.available) && !this.serverFailed; },

  clean(rawText) {
    return cleanForSpeech(rawText, this.getCodeMode());
  },

  chunk(text) {
    return chunkText(text, 240);
  },

  startWatchdog() {
    this.stopWatchdog();
    // Do not run pause/resume heartbeats during active playback; on desktop Linux and mobile,
    // pulsing pause/resume causes Speech Dispatcher or the audio HAL to abort or cancel playback.
    // Instead, this hang watchdog only intervenes if an individual chunk stalls with zero progress for >20s.
    let lastIndex = this.currentIndex;
    let stuckCount = 0;
    this.watchdogTimer = setInterval(() => {
      if (!this.speaking || this.paused || this.useServer() || window.speechSynthesis?.paused) return;
      if (this.currentIndex === lastIndex) {
        stuckCount++;
        if (stuckCount >= 4) { // 4 ticks of 5s = 20s stuck on the same chunk
          console.warn("TTS watchdog: chunk stalled for 20s, advancing to next chunk");
          stuckCount = 0;
          this.currentIndex++;
          this.speakNext();
        }
      } else {
        lastIndex = this.currentIndex;
        stuckCount = 0;
      }
    }, 5000);
  },

  stopWatchdog() {
    if (this.watchdogTimer) {
      clearInterval(this.watchdogTimer);
      this.watchdogTimer = null;
    }
  },

  async acquireWakeLock() {
    if ("wakeLock" in navigator && !this.wakeLock) {
      try {
        this.wakeLock = await navigator.wakeLock.request("screen");
        this.wakeLock.addEventListener("release", () => { this.wakeLock = null; });
      } catch (e) { /* ignore policy errors */ }
    }
  },

  releaseWakeLock() {
    if (this.wakeLock) {
      try { this.wakeLock.release(); } catch (e) {}
      this.wakeLock = null;
    }
  },

  updateMediaSession(title = "Ray Response") {
    if (!("mediaSession" in navigator)) return;
    try {
      navigator.mediaSession.metadata = new MediaMetadata({
        title: title,
        artist: "Ray · Strata",
        album: "Local AI Voice",
      });
      navigator.mediaSession.playbackState = "playing";
      navigator.mediaSession.setActionHandler("play", () => this.resume());
      navigator.mediaSession.setActionHandler("pause", () => this.pause());
      navigator.mediaSession.setActionHandler("stop", () => this.stop());
    } catch (e) {}
  },

  clearMediaSession() {
    if (!("mediaSession" in navigator)) return;
    try {
      navigator.mediaSession.playbackState = "none";
    } catch (e) {}
  },

  startAudioKeepAlive() {
    try {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (!AudioCtx) return;
      if (!this.audioCtx) this.audioCtx = new AudioCtx();
      if (this.audioCtx.state === "suspended") this.audioCtx.resume();
      const buffer = this.audioCtx.createBuffer(1, Math.floor(this.audioCtx.sampleRate * 0.05), this.audioCtx.sampleRate);
      const source = this.audioCtx.createBufferSource();
      source.buffer = buffer;
      source.loop = true;
      source.connect(this.audioCtx.destination);
      source.start();
      this._silentSource = source;
    } catch (e) {}
  },

  stopAudioKeepAlive() {
    if (this._silentSource) {
      try { this._silentSource.stop(); this._silentSource.disconnect(); } catch (e) {}
      this._silentSource = null;
    }
  },

  updateButtonState(speaking) {
    if (!this.activeBtn) return;
    this.activeBtn.classList.toggle("is-speaking", speaking);
    const use = this.activeBtn.querySelector("use");
    if (use) {
      use.setAttribute("href", `${SPRITE}#i-${speaking ? "volume-x" : "volume"}`);
    }
    this.activeBtn.title = speaking ? "Stop reading aloud" : "Read aloud";
    this.activeBtn.setAttribute("aria-label", speaking ? "Stop reading aloud" : "Read aloud");
  },

  stop() {
    if (!window.speechSynthesis) return;
    if (typeof RayFace !== "undefined") RayFace.end(this.speaking && this.currentIndex >= this.queue.length);
    this.stopWatchdog();
    this.releaseWakeLock();
    this.stopAudioKeepAlive();
    this.clearMediaSession();
    try { window.speechSynthesis.cancel(); } catch (e) {}
    const src = this.currentSource;
    this.currentSource = null;
    if (src) { try { src.stop(); } catch (e) {} }
    this.prefetch = [];
    if (this.paused && this.audioCtx) { try { this.audioCtx.resume(); } catch (e) {} }
    this.updateButtonState(false);
    this.speaking = false;
    this.paused = false;
    this.queue = [];
    this.currentIndex = 0;
    this.currentUtterance = null;
    this.activeBtn = null;
    this.activeMsg = null;
  },

  pause() {
    if (!window.speechSynthesis || !this.speaking) return;
    try { window.speechSynthesis.pause(); } catch (e) {}
    if (this.currentSource && this.audioCtx) { try { this.audioCtx.suspend(); } catch (e) {} }
    this.paused = true;
    if (typeof RayFace !== "undefined") RayFace.pause(true);
    if ("mediaSession" in navigator) navigator.mediaSession.playbackState = "paused";
  },

  resume() {
    if (!window.speechSynthesis || !this.speaking) return;
    try { window.speechSynthesis.resume(); } catch (e) {}
    if (this.currentSource && this.audioCtx) { try { this.audioCtx.resume(); } catch (e) {} }
    this.paused = false;
    if (typeof RayFace !== "undefined") RayFace.pause(false);
    if ("mediaSession" in navigator) navigator.mediaSession.playbackState = "playing";
  },

  speakText(rawText, btn = null, msgObj = null) {
    if (!window.speechSynthesis) {
      toast("error", "TTS not supported", "Your browser does not support the Web Speech API.");
      return;
    }

    if (this.speaking) {
      const isTestBtn = Boolean(btn && btn.id === "tts-test-btn");
      const wasSame = !isTestBtn && ((this.activeBtn === btn && btn !== null) || (this.activeMsg === msgObj && msgObj !== null));
      this.stop();
      if (wasSame) return; // Toggle off if clicked on same playing button in chat
    }

    const clean = this.clean(rawText);
    if (!clean) {
      toast("info", "Nothing to read", "The message contains no readable text.");
      return;
    }

    this.queue = this.chunk(clean);
    if (!this.queue.length) return;
    this.prefetch = [];

    this.currentIndex = 0;
    this.speaking = true;
    this.paused = false;
    this.activeBtn = btn;
    this.activeMsg = msgObj;
    this.updateButtonState(true);

    this.acquireWakeLock();
    this.startAudioKeepAlive();
    this.updateMediaSession("Reading response...");
    this.startWatchdog();

    this.speakNext();
  },

  speakNext() {
    if (!this.speaking || this.currentIndex >= this.queue.length) {
      this.stop();
      return;
    }

    const chunk = this.queue[this.currentIndex];
    if (this.useServer()) { this.playServerChunk(this.currentIndex); return; }
    const u = new SpeechSynthesisUtterance(chunk);
    this.currentUtterance = u; // Anchor to avoid V8 GC mid-speech

    const v = this.getVoice();
    if (v) {
      u.voice = v;
      u.lang = v.lang || "en-US";
    } else {
      u.lang = document.documentElement.lang || navigator.language || "en-US";
    }
    u.rate = this.getRate();
    u.pitch = this.getPitch();

    // Ray's face follows the chunk being spoken (web/rayface.js); the test button in Settings has no face
    const orb = this.orb();
    if (orb) {
      u.onstart = () => RayFace.speakText(chunk, u.rate);
      u.onboundary = (e) => RayFace.boundary(e.charIndex);
    }

    u.onend = () => {
      if (orb) RayFace.chunkEnd();
      this.currentIndex++;
      // Yield briefly so browser audio driver cleanly settles before queueing the next utterance
      setTimeout(() => {
        if (this.speaking) this.speakNext();
      }, 25);
    };

    u.onerror = (e) => {
      // If user clicked stop or cancelled explicitly, do not log or continue
      if (!this.speaking) return;

      if (e.error !== "canceled" && e.error !== "interrupted") {
        console.warn("SpeechSynthesis error:", e);
      }
      // On desktop Linux, initial chunk failure suggests missing speech-dispatcher
      if (this.currentIndex === 0 && (e.error === "synthesis-failed" || e.error === "language-unavailable")) {
        const isLinux = /Linux/i.test(navigator.userAgent) && !/Android/i.test(navigator.userAgent);
        if (isLinux) {
          this.stop();
          toast("warn", "Speech synthesis failed", "The browser's speech synthesizer failed. If using Linux/Brave, restart your browser so speech-dispatcher flags take effect.", 6000);
          return;
        }
      }
      // Advance to next chunk rather than dropping the remaining text
      this.currentIndex++;
      if (this.currentIndex < this.queue.length) {
        setTimeout(() => {
          if (this.speaking) this.speakNext();
        }, 35);
      } else {
        this.stop();
      }
    };

    try {
      window.speechSynthesis.speak(u);
    } catch (err) {
      console.error("SpeechSynthesis speak() failed:", err);
      this.stop();
      toast("warn", "Speech blocked", "Click the speaker button to start audio playback.");
    }
  },

  audio() {
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtx) return null;
    if (!this.audioCtx) this.audioCtx = new AudioCtx();
    if (!this.analyser) {
      // the face reads the analyser; the sound reaches the speakers 50 ms later, so it moves just before the voice
      this.analyser = this.audioCtx.createAnalyser();
      this.analyser.fftSize = 1024;
      const delay = this.audioCtx.createDelay(0.2);
      delay.delayTime.value = 0.05;
      this.analyser.connect(delay);
      delay.connect(this.audioCtx.destination);
    }
    return this.audioCtx;
  },

  // chunk i as decoded audio; the next chunk is fetched while this one plays
  fetchChunk(i) {
    if (!this.prefetch[i]) {
      const ctx = this.audio();
      this.prefetch[i] = fetch("v1/audio/speech", {
        method: "POST", headers: headers(true),
        body: JSON.stringify({input: this.queue[i], speed: this.getRate()}),
      }).then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.arrayBuffer();
      }).then((ab) => ctx.decodeAudioData(ab));
      this.prefetch[i].catch(() => {});
    }
    return this.prefetch[i];
  },

  async playServerChunk(i) {
    const queue = this.queue;
    let buf;
    try {
      buf = await this.fetchChunk(i);
    } catch (e) {
      if (!this.speaking || this.queue !== queue) return;
      console.warn("Server voice failed, using the browser voice:", e);
      this.serverFailed = true;                      // until the page reloads
      toast("warn", "Ray's server voice failed", "Reading on with the browser's voice.", 4000);
      this.speakNext();
      return;
    }
    if (!this.speaking || this.queue !== queue || i !== this.currentIndex) return;
    const ctx = this.audio();
    if (ctx.state === "suspended" && !this.paused) { try { await ctx.resume(); } catch (e) {} }
    const src = ctx.createBufferSource();
    src.buffer = buf;
    src.connect(this.analyser);
    this.currentSource = src;
    const orb = this.orb();
    src.onended = () => {
      if (this.currentSource !== src) return;       // stopped
      this.currentSource = null;
      if (orb) RayFace.chunkEnd();
      this.currentIndex++;
      this.speakNext();
    };
    src.start();
    if (orb) RayFace.speakAudio(this.analyser, this.queue[i], ctx, ctx.currentTime, buf.duration);
    if (i + 1 < this.queue.length) this.fetchChunk(i + 1);
  },

  toggleMessage(msg, btn) {
    if (!msg || !msg.text) return;
    this.speakText(msg.text, btn, msg);
  },

  init() {
    if (!window.speechSynthesis) {
      const card = $("tts-settings-card");
      if (card) {
        card.querySelector(".muted.small").textContent = "Web Speech API is not supported in this browser.";
      }
      return;
    }
    const updateVoices = () => this.populateVoiceSelector();
    window.speechSynthesis.onvoiceschanged = updateVoices;
    updateVoices();

    const vSel = $("tts-voice-select");
    if (vSel) {
      vSel.onchange = () => store.set("tts_voice", vSel.value);
    }
    const rSlider = $("tts-rate");
    if (rSlider) {
      rSlider.value = this.getRate();
      const rOut = $("tts-rate-val");
      if (rOut) rOut.textContent = `${Number(rSlider.value).toFixed(2)}x`;
      rSlider.oninput = () => {
        store.set("tts_rate", +rSlider.value);
        if (rOut) rOut.textContent = `${Number(rSlider.value).toFixed(2)}x`;
      };
    }
    const pSlider = $("tts-pitch");
    if (pSlider) {
      pSlider.value = this.getPitch();
      const pOut = $("tts-pitch-val");
      if (pOut) pOut.textContent = Number(pSlider.value).toFixed(2);
      pSlider.oninput = () => {
        store.set("tts_pitch", +pSlider.value);
        if (pOut) pOut.textContent = Number(pSlider.value).toFixed(2);
      };
    }
    const cMode = $("tts-code-mode");
    if (cMode) {
      cMode.value = this.getCodeMode();
      cMode.onchange = () => store.set("tts_code_mode", cMode.value);
    }
    const autoToggle = $("tts-auto-toggle");
    if (autoToggle) {
      autoToggle.setAttribute("aria-checked", String(this.isAutoSpeak()));
      autoToggle.onclick = () => {
        const next = autoToggle.getAttribute("aria-checked") !== "true";
        autoToggle.setAttribute("aria-checked", String(next));
        store.set("tts_auto_speak", next);
        toast("info", `Auto-speak ${next ? "enabled" : "disabled"}`, next ? "Voice prompts (dictated via STT) will be read aloud automatically." : "Tap the speaker icon on any message to listen.", 2500);
      };
    }
    if (typeof RayFace !== "undefined") RayFace.onStop = () => { this.stop(); RayFace.end(false); };   // a click stops it
    // the server's Piper voice: find out once whether it is there; Web Audio may only start after a tap (phones)
    fetch("v1/audio/speech/status", {headers: headers()}).then((r) => (r.ok ? r.json() : null))
      .then((st) => { this.serverTTS = st; }).catch(() => {});
    const unlock = () => { const ctx = this.audio(); if (ctx && ctx.state === "suspended") ctx.resume().catch(() => {}); };
    document.addEventListener("pointerdown", unlock, {once: true, capture: true});
    document.addEventListener("keydown", unlock, {once: true, capture: true});
    const serverToggle = $("tts-server-toggle");
    if (serverToggle) {
      serverToggle.setAttribute("aria-checked", String(this.isServerVoiceOn()));
      serverToggle.onclick = () => {
        const next = serverToggle.getAttribute("aria-checked") !== "true";
        serverToggle.setAttribute("aria-checked", String(next));
        store.set("tts_server", next);
        this.serverFailed = false;
      };
    }
    const orbToggle = $("tts-orb-toggle");
    if (orbToggle) {
      orbToggle.setAttribute("aria-checked", String(this.isOrbOn()));
      orbToggle.onclick = () => {
        const next = orbToggle.getAttribute("aria-checked") !== "true";
        orbToggle.setAttribute("aria-checked", String(next));
        store.set("tts_orb", next);
        if (!next && typeof RayFace !== "undefined") RayFace.end(false);
      };
    }
    const testBtn = $("tts-test-btn");
    if (testBtn) {
      testBtn.onclick = () => {
        const vSel = $("tts-voice-select");
        if (vSel && vSel.value) store.set("tts_voice", vSel.value);
        this.speakText("Good day. I am Ray, running locally on this computer.", testBtn);
      };
    }
  },

  populateVoiceSelector() {
    const sel = $("tts-voice-select");
    if (!sel || !window.speechSynthesis) return;
    const voices = window.speechSynthesis.getVoices();
    const countEl = $("tts-voice-count");
    if (countEl) countEl.textContent = `${voices.length} available`;
    const saved = store.get("tts_voice", "");

    sel.innerHTML = '<option value="">Auto (Ray: Piper HFC female)</option>';

    const knownMeta = {
      amy: { name: "Amy", gender: "Female" },
      bryce: { name: "Bryce", gender: "Male" },
      danny: { name: "Danny", gender: "Male" },
      hfc_female: { name: "HFC", gender: "Female" },
      hfc_male: { name: "HFC", gender: "Male" },
      joe: { name: "Joe", gender: "Male" },
      john: { name: "John", gender: "Male" },
      kathleen: { name: "Kathleen", gender: "Female" },
      kristin: { name: "Kristin", gender: "Female" },
      kusal: { name: "Kusal", gender: "Male" },
      lessac: { name: "Lessac", gender: "Female" },
      ljspeech: { name: "LJSpeech", gender: "Female" },
      mike: { name: "Mike", gender: "Male" },
      norman: { name: "Norman", gender: "Male" },
      reza_ibrahim: { name: "Reza", gender: "Male" },
      ryan: { name: "Ryan", gender: "Male" },
      sam: { name: "Sam", gender: "Male" },
    };

    // Sort so Piper/neural voices appear first, followed by other voices
    const sorted = [...voices].sort((a, b) => {
      const aNeural = /piper|lessac|ryan|natural|neural/i.test(a.name || a.voiceURI);
      const bNeural = /piper|lessac|ryan|natural|neural/i.test(b.name || b.voiceURI);
      if (aNeural && !bNeural) return -1;
      if (!aNeural && bNeural) return 1;
      return (a.name || "").localeCompare(b.name || "");
    });

    sorted.forEach((v) => {
      const opt = document.createElement("option");
      opt.value = v.voiceURI;
      const m = (v.name || "").match(/en_US-([a-z0-9_]+)-(low|medium|high)/i);
      if (m) {
        const id = m[1].toLowerCase();
        const quality = m[2].toLowerCase();
        const meta = knownMeta[id] || { name: id.charAt(0).toUpperCase() + id.slice(1), gender: "Neural" };
        const qLabel = quality === "high" ? "High Quality" : (quality === "medium" ? "Medium" : "Low");
        opt.textContent = `${meta.name} · US ${meta.gender} (${qLabel}) [neural]`;
      } else {
        const isNeural = /piper|lessac|ryan|natural|neural/i.test(v.name || v.voiceURI);
        opt.textContent = `${v.name} (${v.lang})${isNeural ? " [neural]" : (v.localService ? " [local]" : "")}`;
      }
      if (saved && (v.voiceURI === saved || v.name === saved)) opt.selected = true;
      sel.appendChild(opt);
    });
  },
};

// Robust speech transcript merger: handles disjoint phrases, Android cumulative streaming,
// duplicate events, and partial head/tail word overlaps without repeating text.
function mergeSpeechTranscripts(existing, incoming) {
  const ex = (existing || "").trim();
  const inc = (incoming || "").trim();
  if (!inc) return existing || "";
  if (!ex) return incoming || "";

  const exLower = ex.toLowerCase();
  const incLower = inc.toLowerCase();

  // 1. If incoming equals existing, ignore duplicate
  if (exLower === incLower) return existing;

  // 2. If incoming starts with existing (Android cumulative session)
  if (incLower.startsWith(exLower)) {
    return inc;
  }

  // 3. If existing ends with incoming (duplicate trailing phrase)
  if (exLower.endsWith(incLower)) {
    return existing;
  }

  // 4. Overlap check: tail of existing matches head of incoming
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

  // 5. Disjoint: append with space or existing delimiter
  const sep = existing.endsWith(" ") || existing.endsWith("\n") ? "" : " ";
  return `${existing}${sep}${inc}`;
}

// ------------------------------------------------------------------ Speech-to-Text (STT) Native Engine
const STTController = {
  recognition: null,
  mediaRecorder: null,
  mediaStream: null,
  audioChunks: [],
  vadCleanup: null,
  maxTimer: null,
  isRecording: false,
  isPushToTalk: false,
  isTranscribing: false,
  currentTarget: null, // "code" (the only prompt box since the Chat tab went, 2026-10-23)
  baseText: "",
  finalText: "",
  interimText: "",
  silenceTimer: null,
  autoSend: false,
  autoSendTimer: null,
  isInterimTranscribing: false,
  lastInputWasVoice: false,
  lastTranscribedText: "",
  hasWhisper: false,
  whisperModel: null,

  isSupported() {
    return Boolean(
      (navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.MediaRecorder) ||
      window.SpeechRecognition ||
      window.webkitSpeechRecognition
    );
  },

  getLang() {
    return store.get("stt_lang", "") || navigator.language || "en-US";
  },

  getEngine() {
    const pref = store.get("stt_engine", "auto");
    if (pref === "whisper") return "whisper";
    if (pref === "browser") return "browser";
    // "auto" mode:
    // If local Whisper is available, prefer it (works offline, zero cloud leaks, works in Brave Desktop & mobile)
    if (this.hasWhisper) return "whisper";
    if (window.SpeechRecognition || window.webkitSpeechRecognition) return "browser";
    return "whisper";
  },

  isAutoSend() {
    return Boolean(store.get("stt_auto_send", false));
  },

  setAutoSend(val) {
    this.autoSend = !!val;
    store.set("stt_auto_send", this.autoSend);
    const btns = [$("code-mobile-auto-send-btn")];
    for (const btn of btns) {
      if (btn) {
        btn.classList.toggle("is-active", this.autoSend);
        btn.setAttribute("aria-pressed", String(this.autoSend));
        btn.title = `Auto-Send: ${this.autoSend ? "ON (hands-free dictation)" : "OFF"}`;
      }
    }
    const toggle = $("stt-auto-toggle");
    if (toggle) {
      toggle.setAttribute("aria-checked", String(this.autoSend));
    }
  },

  getTargetInput() { return $("code-mobile-input"); },

  getTargetMicBtn() { return $("code-mobile-mic-btn"); },

  dismissKeyboard(target) {
    if (navigator.virtualKeyboard && typeof navigator.virtualKeyboard.hide === "function") {
      try { navigator.virtualKeyboard.hide(); } catch (_) {}
    }
    if (document.activeElement && typeof document.activeElement.blur === "function") {
      try { document.activeElement.blur(); } catch (_) {}
    }
    const ta = this.getTargetInput(target);
    if (ta) {
      try { ta.blur(); } catch (_) {}
      ta.setAttribute("inputmode", "none");
    }
  },

  restoreKeyboard(target) {
    const ta = this.getTargetInput(target);
    if (ta) {
      ta.removeAttribute("inputmode");
    }
  },

  resetSilenceTimer() {
    if (this.silenceTimer) clearTimeout(this.silenceTimer);
    // 4-second silence auto-stop for browser SpeechRecognition
    this.silenceTimer = setTimeout(() => {
      if (this.isRecording) {
        this.stop();
      }
    }, 4000);
  },

  clearSilenceTimer() {
    if (this.silenceTimer) {
      clearTimeout(this.silenceTimer);
      this.silenceTimer = null;
    }
  },

  updateInput() {
    const ta = this.getTargetInput();
    if (!ta) return;
    const spoken = mergeSpeechTranscripts(this.finalText, this.interimText);
    if (spoken && spoken.trim()) {
      this.lastInputWasVoice = true;
      this.lastTranscribedText = spoken.trim();
    }
    ta.value = mergeSpeechTranscripts(this.baseText, spoken);
    ta.style.height = "auto";
    ta.style.height = Math.min(ta.scrollHeight, 160) + "px";
  },

  cancelAutoSendTimer() {
    if (this.autoSendTimer) {
      clearTimeout(this.autoSendTimer);
      this.autoSendTimer = null;
    }
  },

  cancelAutoSendCountdown() {
    this.cancelAutoSendTimer();
  },

  scheduleAutoSend(target) {
    this.cancelAutoSendTimer();
    // Send immediately as requested
    if (typeof codeSend === "function") codeSend();
  },

  async transcribeInterimBlob(blob, target) {
    if (!this.isRecording || this.isInterimTranscribing) return;
    this.isInterimTranscribing = true;

    const fd = new FormData();
    fd.append("file", blob, "interim.webm");
    const lang = this.getLang();
    if (lang) fd.append("language", lang);

    try {
      const res = await fetch("v1/audio/transcriptions", {
        method: "POST",
        headers: headers(),
        body: fd,
      });
      if (res.ok && this.isRecording && this.currentTarget === target) {
        const data = await res.json();
        const text = (data.text || "").trim();
        if (text && this.isRecording && this.currentTarget === target) {
          this.interimText = text;
          this.updateInput();
        }
      }
    } catch (e) {
      // Non-fatal interim transcription
    } finally {
      this.isInterimTranscribing = false;
    }
  },

  setupVAD(stream, callbacks = {}) {
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtx) return null;
    try {
      const ctx = new AudioCtx();
      const src = ctx.createMediaStreamSource(stream);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 512;
      analyser.smoothingTimeConstant = 0.3;
      src.connect(analyser);

      const data = new Uint8Array(analyser.frequencyBinCount);
      let hadSpeech = false;
      let silenceSince = null;
      let active = true;

      const interval = setInterval(() => {
        if (!active) return;
        analyser.getByteFrequencyData(data);
        let sum = 0;
        for (let i = 0; i < data.length; i++) sum += data[i];
        const avg = sum / data.length;

        if (avg > 6) {
          hadSpeech = true;
          silenceSince = null;
          if (callbacks.onSpeech) callbacks.onSpeech();
        } else if (hadSpeech) {
          if (!silenceSince) {
            silenceSince = Date.now();
            if (callbacks.onPause) callbacks.onPause();
          } else {
            const silentMs = Date.now() - silenceSince;
            if (silentMs > 1000 && silentMs < 1200) {
              if (callbacks.onPause) callbacks.onPause();
            } else if (silentMs > 3200) {
              active = false;
              if (callbacks.onSilence) callbacks.onSilence();
            }
          }
        }
      }, 150);

      return () => {
        active = false;
        clearInterval(interval);
        try { ctx.close(); } catch (e) {}
      };
    } catch (e) {
      return null;
    }
  },

  async startMediaRecorder(target) {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !window.MediaRecorder) {
      toast("warn", "Microphone recording unsupported", "Your browser does not support local audio recording via MediaRecorder.");
      return;
    }

    this.cancelAutoSendTimer();
    this.dismissKeyboard(target);

    if (this.isRecording) {
      if (this.currentTarget === target) return;
      this.stop();
    }

    if (typeof TTSController !== "undefined" && TTSController.speaking) {
      TTSController.stop();
    }

    this.currentTarget = target;
    const ta = this.getTargetInput(target);
    this.baseText = ta ? ta.value : "";
    this.finalText = "";
    this.interimText = "";

    try {
      this.mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          sampleRate: 16000,
          echoCancellation: true,
          noiseSuppression: true,
        },
      });
    } catch (err) {
      toast("warn", "Microphone access blocked", "Please allow microphone access in your browser settings to use voice typing.");
      this.cleanup();
      return;
    }

    let mimeType = "";
    const types = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"];
    for (const t of types) {
      if (MediaRecorder.isTypeSupported(t)) {
        mimeType = t;
        break;
      }
    }

    try {
      this.audioChunks = [];
      this.mediaRecorder = mimeType ? new MediaRecorder(this.mediaStream, { mimeType }) : new MediaRecorder(this.mediaStream);
    } catch (e) {
      try {
        this.mediaRecorder = new MediaRecorder(this.mediaStream);
      } catch (err) {
        toast("error", "Recording error", "Failed to initialize MediaRecorder: " + (err.message || err));
        this.cleanup();
        return;
      }
    }

    this.mediaRecorder.ondataavailable = (e) => {
      if (e.data && e.data.size > 0) {
        this.audioChunks.push(e.data);
      }
    };

    this.mediaRecorder.onstop = async () => {
      const chunks = this.audioChunks.slice();
      this.audioChunks = [];
      if (this.mediaStream) {
        this.mediaStream.getTracks().forEach((t) => t.stop());
        this.mediaStream = null;
      }
      if (typeof this.vadCleanup === "function") {
        this.vadCleanup();
        this.vadCleanup = null;
      }
      if (this.maxTimer) {
        clearTimeout(this.maxTimer);
        this.maxTimer = null;
      }

      const blob = new Blob(chunks, { type: this.mediaRecorder?.mimeType || mimeType || "audio/webm" });
      if (blob.size < 500) {
        this.cleanup();
        return;
      }
      await this.transcribeBlob(blob, target);
    };

    this.isRecording = true;
    this.updateMicUI(true);

    let lastInterimTime = Date.now();
    this.vadCleanup = this.setupVAD(this.mediaStream, {
      onSpeech: () => {
        if (Date.now() - lastInterimTime > 2500 && this.audioChunks.length >= 4 && !this.isInterimTranscribing) {
          lastInterimTime = Date.now();
          const interimBlob = new Blob(this.audioChunks.slice(), {
            type: this.mediaRecorder?.mimeType || mimeType || "audio/webm",
          });
          this.transcribeInterimBlob(interimBlob, target);
        }
      },
      onPause: () => {
        if (Date.now() - lastInterimTime > 1500 && this.audioChunks.length >= 3 && !this.isInterimTranscribing) {
          lastInterimTime = Date.now();
          const interimBlob = new Blob(this.audioChunks.slice(), {
            type: this.mediaRecorder?.mimeType || mimeType || "audio/webm",
          });
          this.transcribeInterimBlob(interimBlob, target);
        }
      },
      onSilence: () => {
        if (this.isRecording) {
          this.stop();
        }
      },
    });

    this.maxTimer = setTimeout(() => {
      if (this.isRecording) this.stop();
    }, 60000);

    try {
      this.mediaRecorder.start(250);
    } catch (e) {
      this.mediaRecorder.start();
    }
  },

  async transcribeBlob(blob, target) {
    this.isTranscribing = true;
    this.updateTranscribingUI(true);

    const fd = new FormData();
    fd.append("file", blob, "recording.webm");
    const lang = this.getLang();
    if (lang) fd.append("language", lang);

    try {
      const res = await fetch("v1/audio/transcriptions", {
        method: "POST",
        headers: headers(),
        body: fd,
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error?.message || `HTTP ${res.status}`);
      }
      const data = await res.json();
      const text = (data.text || "").trim();
      if (text) {
        this.finalText = text;
        this.interimText = "";
        this.lastInputWasVoice = true;
        this.lastTranscribedText = text;

        const targetToSend = target || this.currentTarget || "code";
        // Always populate the text box visibly first so the user sees the recognized text!
        this.updateInput();
        const ta = this.getTargetInput(targetToSend);
        if (ta) {
          this.baseText = ta.value;
          try {
            ta.selectionStart = ta.selectionEnd = ta.value.length;
          } catch (_) {}
        }

        if (this.autoSend) {
          this.scheduleAutoSend(targetToSend);
        } else {
          this.finalText = "";
        }
      }
    } catch (e) {
      toast("error", "Transcription error", e.message || String(e));
    } finally {
      this.isTranscribing = false;
      this.updateTranscribingUI(false);
      this.cleanup();
    }
  },

  async startBrowserSpeech(target) {
    const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRec) {
      if (this.hasWhisper) {
        return this.startMediaRecorder(target);
      }
      toast("warn", "Speech recognition unavailable", "Your browser does not support native speech recognition.");
      return;
    }

    this.cancelAutoSendTimer();
    this.dismissKeyboard(target);

    if (this.isRecording) {
      if (this.currentTarget === target) return;
      this.stop();
    }

    if (typeof TTSController !== "undefined" && TTSController.speaking) {
      TTSController.stop();
    }

    this.currentTarget = target;
    const ta = this.getTargetInput(target);
    this.baseText = ta ? ta.value : "";
    this.finalText = "";
    this.interimText = "";

    try {
      this.recognition = new SpeechRec();
      const isAndroid = /Android/i.test(navigator.userAgent);
      this.recognition.continuous = !isAndroid;
      this.recognition.interimResults = true;
      this.recognition.lang = this.getLang();

      this.recognition.onstart = () => {
        this.isRecording = true;
        this.updateMicUI(true);
        this.resetSilenceTimer();
      };

      this.recognition.onresult = (event) => {
        this.resetSilenceTimer();
        let finalStr = "";
        let interimStr = "";

        for (let i = 0; i < event.results.length; ++i) {
          const res = event.results[i];
          if (!res || !res[0]) continue;
          const transcript = (res[0].transcript || "").trim();
          if (!transcript) continue;

          if (res.isFinal) {
            finalStr = mergeSpeechTranscripts(finalStr, transcript);
          } else {
            interimStr = mergeSpeechTranscripts(interimStr, transcript);
          }
        }

        this.finalText = finalStr;
        this.interimText = interimStr;
        this.updateInput();
      };

      this.recognition.onerror = async (event) => {
        const err = event.error;
        if (err === "no-speech") return;

        let isBrave = false;
        try {
          if (navigator.brave && typeof navigator.brave.isBrave === "function") {
            isBrave = await navigator.brave.isBrave();
          } else if (window.chrome && !window.chrome.webstore && /Brave/i.test(navigator.userAgent)) {
            isBrave = true;
          }
        } catch (e) {
          isBrave = false;
        }

        if (err === "service-not-allowed" || err === "network") {
          if (this.hasWhisper) {
            toast("info", "Using Local Whisper STT", "Browser speech service unavailable; switched to local Whisper.");
            this.cleanup();
            store.set("stt_engine", "whisper");
            const engSel = $("stt-engine-select");
            if (engSel) engSel.value = "whisper";
            return this.startMediaRecorder(target);
          }
          if (isBrave) {
            this.openBraveGuide();
            this.cleanup();
            return;
          }
          toast("error", "Speech recognition failed", `Network or service issue (${err}). Make sure internet is connected.`);
        } else if (err === "not-allowed") {
          if (isBrave && !this.hasWhisper) {
            this.openBraveGuide();
            this.cleanup();
            return;
          }
          toast("warn", "Microphone access blocked", "Please allow microphone access in your browser settings to use voice typing.");
        } else if (err !== "aborted") {
          toast("warn", "Speech recognition error", `Error: ${err}`);
        }
        this.cleanup();
      };

      this.recognition.onend = () => {
        const hadRecording = this.isRecording;
        const targetWas = this.currentTarget || "code";
        const hadFinalSpoken = Boolean((this.finalText + " " + this.interimText).trim());
        const spokenText = mergeSpeechTranscripts(this.finalText, this.interimText).trim();

        if (hadRecording && hadFinalSpoken && spokenText) {
          this.finalText = spokenText;
          this.interimText = "";
          this.lastInputWasVoice = true;
          this.lastTranscribedText = spokenText;

          // Always populate the text box visibly first so user sees it!
          this.updateInput();
          const ta = this.getTargetInput(targetWas);
          if (ta) {
            this.baseText = ta.value;
            try {
              ta.selectionStart = ta.selectionEnd = ta.value.length;
            } catch (_) {}
          }

          this.cleanup();

          if (this.autoSend) {
            this.scheduleAutoSend(targetWas);
          } else {
            this.finalText = "";
          }
          return;
        }

        this.cleanup();
      };

      this.recognition.start();
    } catch (e) {
      toast("error", "Voice typing error", e.message || String(e));
      this.cleanup();
    }
  },

  async start(target = "code") {
    this.dismissKeyboard(target);
    const engine = this.getEngine();
    if (engine === "whisper") {
      return this.startMediaRecorder(target);
    }
    return this.startBrowserSpeech(target);
  },

  stop() {
    this.clearSilenceTimer();
    if (this.maxTimer) {
      clearTimeout(this.maxTimer);
      this.maxTimer = null;
    }
    if (typeof this.vadCleanup === "function") {
      this.vadCleanup();
      this.vadCleanup = null;
    }
    if (this.mediaRecorder && this.mediaRecorder.state !== "inactive") {
      try {
        this.mediaRecorder.stop();
      } catch (e) {}
      return;
    }
    if (this.recognition) {
      try {
        this.recognition.stop();
      } catch (e) {}
    }
  },

  cleanup() {
    this.clearSilenceTimer();
    if (this.maxTimer) {
      clearTimeout(this.maxTimer);
      this.maxTimer = null;
    }
    if (typeof this.vadCleanup === "function") {
      this.vadCleanup();
      this.vadCleanup = null;
    }
    if (this.mediaStream) {
      this.mediaStream.getTracks().forEach((t) => t.stop());
      this.mediaStream = null;
    }
    this.mediaRecorder = null;
    this.audioChunks = [];
    this.isRecording = false;
    this.isPushToTalk = false;
    this.updateMicUI(false);
    this.updateTranscribingUI(false);
    this.interimText = "";
    this.recognition = null;
    const ta = this.getTargetInput();
    if (ta) {
      setTimeout(() => {
        if (!this.isRecording) {
          ta.removeAttribute("inputmode");
        }
      }, 400);
    }
  },

  toggle(target) {
    if (this.isTranscribing) return;
    this.cancelAutoSendTimer();
    this.dismissKeyboard(target);
    if (this.isRecording && this.currentTarget === target) {
      this.stop();
    } else {
      this.start(target);
    }
  },

  updateMicUI(recording) {
    const btn = this.getTargetMicBtn();
    if (btn) {
      btn.classList.toggle("is-recording", recording);
      btn.setAttribute("aria-pressed", String(recording));
      btn.title = recording ? "Listening... (Click to stop)" : "Voice typing (Click to speak / Hold to talk)";
      const use = btn.querySelector("use");
      if (use) {
        use.setAttribute("href", `${SPRITE}#i-${recording ? "mic-off" : "mic"}`);
      }
    }
  },

  updateTranscribingUI(transcribing) {
    const btn = this.getTargetMicBtn();
    if (btn) {
      btn.classList.toggle("is-transcribing", transcribing);
      if (transcribing) {
        btn.title = "Transcribing speech with Whisper...";
      }
    }
  },

  openBraveGuide() {
    const d = $("brave-stt-dialog");
    if (d) {
      const banner = $("brave-stt-whisper-banner");
      if (banner) {
        banner.style.display = this.hasWhisper ? "block" : "none";
      }
      const modelSpan = $("brave-dialog-model-name");
      if (modelSpan && this.whisperModel) {
        modelSpan.textContent = this.whisperModel;
      }
      if (typeof d.showModal === "function") d.showModal();
      else d.setAttribute("open", "");
    }
  },

  closeBraveGuide() {
    const d = $("brave-stt-dialog");
    if (d) {
      if (typeof d.close === "function") d.close();
      else d.removeAttribute("open");
    }
  },

  updateEngineUI() {
    const engSel = $("stt-engine-select");
    const status = $("stt-engine-status");
    if (engSel) {
      engSel.value = store.get("stt_engine", "auto");
    }
    if (status) {
      if (this.hasWhisper) {
        status.textContent = `Local Whisper ready (${this.whisperModel || "ggml-base.bin"}). 100% offline & private.`;
        status.style.color = "var(--st-accent, #0ea5e9)";
      } else {
        status.textContent = "Local Whisper model not detected. Using Browser Web Speech API.";
        status.style.color = "var(--st-muted)";
      }
    }
    const banner = $("brave-stt-whisper-banner");
    if (banner) {
      banner.style.display = this.hasWhisper ? "block" : "none";
    }
  },

  bindDualMode(btn, target) {
    if (!btn) return;
    let pressTimer = null;
    let isHold = false;
    let didAction = false;

    const onPointerDown = (e) => {
      if (e.button !== undefined && e.button !== 0) return;
      this.dismissKeyboard(target);
      didAction = false;
      isHold = false;
      pressTimer = setTimeout(() => {
        isHold = true;
        this.isPushToTalk = true;
        if (!this.isRecording) {
          this.start(target);
        }
      }, 400);
    };

    const onPointerUp = (e) => {
      if (pressTimer) {
        clearTimeout(pressTimer);
        pressTimer = null;
      }
      if (isHold) {
        isHold = false;
        this.isPushToTalk = false;
        if (this.isRecording && this.currentTarget === target) {
          this.stop();
        }
        didAction = true;
        e.preventDefault();
      }
    };

    const onClick = (e) => {
      this.dismissKeyboard(target);
      if (didAction) {
        didAction = false;
        e.preventDefault();
        return;
      }
      this.isPushToTalk = false;
      this.toggle(target);
    };

    btn.addEventListener("pointerdown", onPointerDown);
    btn.addEventListener("pointerup", onPointerUp);
    btn.addEventListener("pointercancel", onPointerUp);
    btn.addEventListener("click", onClick);
  },

  async init() {
    this.autoSend = this.isAutoSend();
    this.setAutoSend(this.autoSend);

    const toggleAutoSend = () => {
      const next = !this.autoSend;
      this.setAutoSend(next);
      toast("info", `Auto-send ${next ? "enabled" : "disabled"}`, next ? "Hands-free: messages send automatically when dictation stops." : "Manual send mode: transcribed text stays in composer.", 2500);
    };

    const codeAutoSendBtn = $("code-mobile-auto-send-btn");
    if (codeAutoSendBtn) codeAutoSendBtn.onclick = toggleAutoSend;

    const sttAutoToggle = $("stt-auto-toggle");
    if (sttAutoToggle) sttAutoToggle.onclick = toggleAutoSend;

    // Engine selection
    const engSel = $("stt-engine-select");
    if (engSel) {
      engSel.value = store.get("stt_engine", "auto");
      engSel.onchange = () => {
        store.set("stt_engine", engSel.value);
        toast("info", "Speech Recognition Engine", `Set to ${engSel.options[engSel.selectedIndex]?.text || engSel.value}`);
      };
    }

    // Language selection
    const langSel = $("stt-lang-select");
    if (langSel) {
      const savedLang = store.get("stt_lang", "");
      if (savedLang) {
        langSel.value = savedLang;
      } else {
        const browserLang = navigator.language || "en-US";
        const match = [...langSel.options].find((o) => o.value === browserLang || o.value.startsWith(browserLang.slice(0, 2)));
        if (match) langSel.value = match.value;
      }
      langSel.onchange = () => {
        store.set("stt_lang", langSel.value);
        toast("info", "Dictation language", `Language set to ${langSel.options[langSel.selectedIndex]?.text || langSel.value}`);
      };
    }

    // Brave Dialog controls
    const braveGuideBtn = $("brave-guide-btn");
    if (braveGuideBtn) {
      braveGuideBtn.onclick = () => this.openBraveGuide();
    }
    const braveCloseBtn = $("brave-dialog-close-btn");
    if (braveCloseBtn) {
      braveCloseBtn.onclick = () => this.closeBraveGuide();
    }
    const braveOkBtn = $("brave-dialog-ok-btn");
    if (braveOkBtn) {
      braveOkBtn.onclick = () => this.closeBraveGuide();
    }
    const braveUseWhisperBtn = $("brave-use-whisper-btn");
    if (braveUseWhisperBtn) {
      braveUseWhisperBtn.onclick = () => {
        store.set("stt_engine", "whisper");
        if (engSel) engSel.value = "whisper";
        this.closeBraveGuide();
        toast("success", "Local Whisper STT Activated", "Speech recognition will now run 100% locally on your PC.");
      };
    }
    const braveCopyBtn = $("brave-copy-flags-btn");
    if (braveCopyBtn) {
      braveCopyBtn.onclick = () => {
        copyText("--enable-speech-dispatcher\n--enable-features=BraveOnDeviceSpeechRecognition,OnDeviceWebSpeech,OnDeviceSpeechRecognition", braveCopyBtn);
      };
    }

    // Bind Dual-mode interaction to mic buttons
    this.bindDualMode($("code-mobile-mic-btn"), "code");

    // Cancel auto-send timer when user interacts with text boxes (typing, clicking, tapping to edit)
    const cancelOnInteract = () => {
      if (this.autoSendTimer) {
        this.cancelAutoSendTimer();
      }
    };
    $("code-mobile-input")?.addEventListener("input", cancelOnInteract);
    $("code-mobile-input")?.addEventListener("click", cancelOnInteract);
    $("code-mobile-input")?.addEventListener("pointerdown", cancelOnInteract);

    // Restore virtual keyboard when user intentionally interacts directly with text boxes
    const enableKeyboardOnTouch = (el) => {
      if (!el) return;
      const restore = () => {
        el.removeAttribute("inputmode");
      };
      el.addEventListener("pointerdown", restore);
      el.addEventListener("touchstart", restore, { passive: true });
      el.addEventListener("focus", restore);
    };
    enableKeyboardOnTouch($("code-mobile-input"));

    // Fetch status of local Whisper engine asynchronously
    try {
      const r = await fetch("v1/audio/status", { headers: headers() });
      if (r.ok) {
        const st = await r.json();
        this.hasWhisper = !!st.available;
        this.whisperModel = st.model || null;
      }
    } catch (e) {
      this.hasWhisper = false;
    }
    this.updateEngineUI();
  },
};

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
  if (location.hash.slice(1) !== tab) history.replaceState(null, "", tab === "code" ? location.pathname : `#${tab}`);
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

// ------------------------------------------------------------------ Code: shared CLI session (tools/dl_sessiond.py)
// The same session runs in the terminal (dl_cli.py --attach): this tab is one more client of it.
// ?session=NAME shows another daemon session (the agent bench's bench-* sessions); the default is the shared one
const CODE_SESSION = /^[A-Za-z0-9_.-]{1,64}$/.test(new URLSearchParams(location.search).get("session") || "")
  ? new URLSearchParams(location.search).get("session") : "dl-ai-code";
const code = { conn: null, state: {}, client: "", cur: null, retry: 0, renderQueued: false, approvals: {}, turnFromVoice: false, replaying: false, lastSpokenText: "" };
// thinking blocks start open; the ones you close stay closed (per session, kept in this browser)
const thinkClosedKey = `code.thinkClosed.${CODE_SESSION}`;
const codeThinkClosed = new Set(store.get(thinkClosedKey, []));
function codeSaveThinkState() { store.set(thinkClosedKey, [...codeThinkClosed].slice(-500)); }

function codeFeed() { return $("code-mobile-messages"); }
// a box with its own scroll bar (the thinking text) follows new text while you are at its bottom; scrolled up, it stays
function followText(box, text) {
  const atEnd = box.scrollHeight - box.scrollTop - box.clientHeight < 24;
  box.textContent = text;
  if (atEnd) box.scrollTop = box.scrollHeight;
}
// The feed follows the answer while the reader has not left (#4014, from upstream 0.2.7). Asking "within 80 px of the
// bottom?" pulled the view back after every wheel notch (about 100 px) while text streamed in; now the reader's own input
// (wheel up, a finger, a key moving up, the scrollbar) lets go at once, and a scroll back to the bottom follows again.
const FOLLOW_SLACK = 24, FAR_AWAY = 400, INPUT_WINDOW_MS = 400;
let codeStick = true, codeLastInput = 0;
function followAfterScroll(distance, wasFollowing, msSinceInput) {
  if (distance <= FOLLOW_SLACK) return true;
  if (msSinceInput <= INPUT_WINDOW_MS || distance > FAR_AWAY) return false;
  return wasFollowing;
}
function codeAtBottom() { return codeStick; }
function codeScroll(force) {
  const f = codeFeed();
  if (!f) return;
  if (force) codeStick = true;
  if (codeStick) f.scrollTop = f.scrollHeight;
}
(function watchCodeReader() {
  const f = codeFeed();
  if (!f) return;
  const touch = () => { codeLastInput = Date.now(); };
  f.addEventListener("wheel", (e) => { touch(); if (e.deltaY < 0 && f.scrollTop > 0) codeStick = false; }, { passive: true });
  f.addEventListener("touchmove", touch, { passive: true });
  f.addEventListener("pointerdown", touch, { passive: true });
  f.addEventListener("keydown", (e) => {
    touch();
    if (["PageUp", "ArrowUp", "Home"].includes(e.key) && f.scrollTop > 0) codeStick = false;
  });
  f.addEventListener("scroll", () => {
    codeStick = followAfterScroll(f.scrollHeight - f.scrollTop - f.clientHeight, codeStick, Date.now() - codeLastInput);
  }, { passive: true });
})();

function codeCard(cls, html) {
  const el = document.createElement("div");
  el.className = `code-mobile-card ${cls}`;
  el.innerHTML = html;
  const stick = codeAtBottom();
  codeFeed().appendChild(el);
  if (stick) codeScroll(true);
  return el;
}

function codeAssistant() {
  if (code.cur) return code.cur;
  const el = codeCard("code-mobile-card--assistant cs-reply",
    `<details class="cs-think" hidden open><summary>Thinking</summary><div class="cs-think-body"></div></details><div class="cs-text md"></div>` +
    `<div class="code-card-actions">` +
    `<button type="button" class="st-btn st-btn--icon st-btn--sm code-card-action" data-code-copy title="Copy answer" aria-label="Copy answer">${icon("copy")}</button>` +
    `<button type="button" class="st-btn st-btn--icon st-btn--sm code-card-action" data-code-speak title="Read aloud" aria-label="Read aloud">${icon("volume")}</button>` +
    `</div>`);
  code.cur = { el, thinking: "", text: "", fromVoice: Boolean(code.turnFromVoice) };
  return code.cur;
}

function codeEnd() {                                      // close the open reply block, drawn in full
  if (code.cur) {
    const cur = code.cur;
    codeRenderCur(cur);
  }
  code.cur = null;
}

function codeOnTurnEnd() {
  if (TTSController.isAutoSpeak() && code.turnFromVoice && !code.replaying) {
    const cards = codeFeed() ? codeFeed().querySelectorAll(".code-mobile-card--assistant") : [];
    if (cards.length) {
      const lastCard = cards[cards.length - 1];
      const textEl = lastCard.querySelector(".cs-text") || lastCard.querySelector(".code-mobile-card-body");
      const sp = lastCard.querySelector("[data-code-speak]") || $("code-speak-btn");
      if (textEl) {
        const textToSpeak = (textEl.innerText || textEl.textContent || "").trim();
        if (textToSpeak && textToSpeak !== code.lastSpokenText) {
          code.lastSpokenText = textToSpeak;
          TTSController.speakText(textToSpeak, sp);
        }
      }
    }
  }
  code.turnFromVoice = false;
  if (typeof RayFace !== "undefined" && !TTSController.speaking) RayFace.end(false);   // thought, but nothing to say
}

function codeRenderCur(block) {
  code.renderQueued = false;
  const c = block || code.cur;
  if (!c) return;
  const stick = codeAtBottom();
  const think = c.el.querySelector(".cs-think");
  if (c.thinking) { think.hidden = false; followText(think.querySelector(".cs-think-body"), c.thinking); }
  c.el.querySelector(".cs-text").innerHTML = c.text ? markdown(c.text) : "";
  if (stick) codeScroll(true);
}
function codeQueueRender() {
  if (!code.renderQueued) { code.renderQueued = true; requestAnimationFrame(() => codeRenderCur()); }
}

function codeBar(label, used, total, pct) {
  const level = pct >= 90 ? "bad" : pct >= 75 ? "warn" : "ok";
  return `<div class="cs-bar"><span class="cs-bar-label">${esc(label)}</span>
    <span class="cs-bar-track"><span class="cs-bar-fill cs-bar-fill--${level}" style="width:${Math.min(100, pct).toFixed(1)}%"></span></span>
    <span class="cs-bar-val">${used.toFixed(1)} / ${total.toFixed(1)} GB</span></div>`;
}

function codeHealth(d) {
  const eng = d.engine || d.strata || {};
  const rows = [
    d.ram ? codeBar("RAM", d.ram.used_gb, d.ram.total_gb, d.ram.pct) : "",
    d.vram ? codeBar("VRAM", d.vram.used_gb, d.vram.total_gb, d.vram.pct) : "",
    d.swap ? codeBar("Swap", d.swap.used_gb, d.swap.total_gb, d.swap.pct) : "",
  ].join("");
  const cpu = d.cpu ? `<div class="cs-kv"><span>CPU load</span><span>${(d.cpu.load_1m || 0).toFixed(2)} (${d.cpu.cores} cores)</span></div>` : "";
  const engine = eng.status ? `<div class="cs-kv"><span>Engine</span><span>${esc(eng.status)} ${esc(eng.model || "")}</span></div>` : "";
  return `<div class="code-mobile-card-header"><span class="role-tag">System health</span></div>${rows}${cpu}${engine}`;
}

function codeApprovalCard(ev) {
  // "mcp-always": sending email or sharing - the whole message is shown (a YOLO session never asks)
  const mail = ev.kind === "mcp-always";
  const [reason, foreign] = String(ev.reason || "").split(" · ADDRESS NOT FROM YOU: ");
  const el = codeCard("cs-approval", (mail ? `
    <div class="cs-approval-title">${/^scheduled/.test(reason) ? "⏰ Schedule this?" : /permission|access|share/i.test(String(ev.summary).split("\n")[0]) ? "🔗 Share this?" : "✉ Send this?"}</div>
    <pre class="cs-approval-mail">${esc(ev.summary)}</pre>
    <div class="cs-approval-reason">${esc(reason)}${foreign ? ` · <span class="cs-approval-foreign">address not from you: ${esc(foreign)}</span>` : ""}</div>` : `
    <div class="cs-approval-title">${ev.kind === "plan" ? "📋" : "⚠"} ${esc(ev.summary)}</div>
    <div class="cs-approval-reason">${esc(ev.reason || "")}</div>`) + `
    <div class="cs-approval-actions">
      <button type="button" class="st-btn st-btn--primary st-btn--sm" data-ok="1">${ev.kind === "plan" ? "Execute" : "Approve"}</button>
      <button type="button" class="st-btn st-btn--secondary st-btn--sm" data-ok="0">${ev.kind === "plan" ? "Keep planning" : "Deny"}</button>
    </div>`);
  for (const b of el.querySelectorAll("button")) {
    b.onclick = () => codeOp(b.dataset.ok === "1" ? "approve" : "deny", { id: ev.id });
  }
  code.approvals[ev.id] = el;
}

function codeResolve(id, ok) {
  const el = code.approvals[id];
  if (!el) return;
  el.classList.add("cs-approval--done");
  const act = el.querySelector(".cs-approval-actions");
  if (act) act.innerHTML = `<span class="muted small">${ok ? "Approved" : "Not approved"}</span>`;
  delete code.approvals[id];
}

// The active plan (PLAN.md) the done check holds the agent to: "PLAN 12/34", red when it has a Blocked: line.
function codePlanChip(plan) {
  if (!plan) return "";
  const total = (plan.done || 0) + (plan.open || 0);
  const label = plan.blocked ? "BLOCKED" : `PLAN ${plan.done || 0}/${total}`;
  const tip = `${plan.file}: ${plan.done || 0} steps done, ${plan.open || 0} open` + (plan.blocked ? ", blocked" : "");
  return ` <span class="cs-mode cs-mode--progress${plan.blocked ? " cs-mode--blocked" : ""}" title="${esc(tip)}">${esc(label)}</span>`;
}

function codeSetState(st) {
  code.state = st || {};
  const meta = $("code-scaffold-meta");
  if (meta) {
    const mode = (code.state.mode || "act").toUpperCase();
    const eff = code.state.effort ? ` <span class="cs-mode cs-mode--effort" title="Thinking level: ${esc(code.state.effort)}">${esc(code.state.effort.toUpperCase())}</span>` : "";
    meta.innerHTML = `<span class="cs-mode cs-mode--${esc(code.state.mode || "act")}">${mode}</span>` +
      eff +
      (code.state.yolo ? ` <span class="cs-mode cs-mode--yolo">YOLO</span>` : "") +
      codePlanChip(code.state.plan) +
      (code.state.mcp || []).map((m) => ` <span class="cs-mode cs-mode--mcp" title="${esc(m.description)} (${esc(m.why || "on")})">${esc(m.name)}</span>`).join("") +
      ` <code title="${esc(code.state.workspace || "")}">${esc((code.state.workspace || "").split("/").slice(-2).join("/"))}</code>`;
  }
  const busy = !!code.state.busy;
  if ($("code-stop-btn")) $("code-stop-btn").hidden = !busy;
  codeBarFit();
  document.querySelector(".code-dot")?.classList.toggle("code-dot--busy", busy);
}

// The session line in the Code bar goes to a row of its own when it would be cut (a narrow side-by-side pane, many
// MCP chips): measured in its one-row form, so it moves back up as soon as there is room again.
function codeBarFit() {
  const bar = document.querySelector(".code-terminal-bar"), meta = $("code-scaffold-meta");
  if (!bar || !meta) return;
  bar.classList.remove("code-terminal-bar--stacked");
  if (meta.scrollWidth > meta.clientWidth + 1) bar.classList.add("code-terminal-bar--stacked");
}
if (window.ResizeObserver && document.querySelector(".code-terminal-bar")) {
  let barW = 0;                                            // its height changes when it stacks: react to width only
  new ResizeObserver((es) => {
    const w = Math.round(es[0].contentRect.width);
    if (w !== barW) { barW = w; codeBarFit(); }
  }).observe(document.querySelector(".code-terminal-bar"));
}

function codeEvent(ev, replay) {
  switch (ev.type) {
    case "thinking": {
      const c = codeAssistant();
      if (ev.block != null && c.el.dataset.block == null) {
        c.el.dataset.block = ev.block;
        c.el.querySelector(".cs-think").open = !codeThinkClosed.has(ev.block);
      }
      c.thinking += ev.text;
      codeQueueRender();
      break;
    }
    case "text": codeAssistant().text += ev.text; codeQueueRender(); break;
    case "user":
      codeEnd();
      {
        const prompt = ev.seq != null && ev.text && !/^[\/!]/.test(ev.text);   // a prompt: it can be gone back to
        const card = codeCard("code-mobile-card--user", `<div class="code-mobile-card-body">${esc(ev.text)}</div>` + (prompt ? `
          <div class="code-card-actions cs-prompt-actions">
            <button type="button" class="st-btn st-btn--icon st-btn--sm code-card-action" data-prompt-edit title="Edit this prompt and run it again" aria-label="Edit this prompt">✎</button>
            <button type="button" class="st-btn st-btn--icon st-btn--sm code-card-action" data-prompt-rewind title="Rewind to before this prompt" aria-label="Rewind to before this prompt">↶</button>
            <button type="button" class="st-btn st-btn--icon st-btn--sm code-card-action" data-prompt-branch title="Branch: keep the whole conversation in Sessions, go on from before this prompt" aria-label="Branch from before this prompt">⑂</button>
          </div>` : ""));
        if (prompt) { card.dataset.seq = ev.seq; card.dataset.prompt = ev.text; }
      }
      if (!replay && ev.origin && ev.origin === code.client) codeScroll(true);   // #4014: what you sent is shown, even scrolled up
      break;
    case "tool_call": {
      codeEnd();
      const args = Object.entries(ev.args || {}).map(([k, v]) => `${k}=${String(v).slice(0, 60)}`).join(", ");
      const el = codeCard("cs-tool", `<details><summary><span class="cs-tool-name">◆ ${esc(ev.name)}</span>
        <span class="cs-tool-args">${esc(args)}</span></summary><pre class="cs-tool-result">…</pre></details>`);
      el.dataset.callId = ev.id || "";
      break;
    }
    case "tool_result": {
      const cards = codeFeed().querySelectorAll(".cs-tool");
      const el = [...cards].reverse().find((c) => c.dataset.callId === (ev.id || "")) || cards[cards.length - 1];
      if (el) {
        el.querySelector(".cs-tool-result").textContent = ev.text + (ev.truncated ? "\n…" : "");
        if (/^(Error|Denied|SECURITY ERROR|SYNTAX ERROR)/.test(ev.text)) el.classList.add("cs-tool--err");
      }
      break;
    }
    case "output":
      codeEnd();
      codeCard("code-mobile-card--assistant", `<div class="code-mobile-card-header"><span class="role-tag">${esc(ev.title || "")}</span></div>
        <div class="code-mobile-card-body">${esc(ev.text || "")}</div>
        <div class="code-card-actions">
          <button type="button" class="st-btn st-btn--icon st-btn--sm code-card-action" data-code-copy title="Copy output" aria-label="Copy output">${icon("copy")}</button>
          <button type="button" class="st-btn st-btn--icon st-btn--sm code-card-action" data-code-speak title="Read aloud" aria-label="Read aloud">${icon("volume")}</button>
        </div>`);
      break;
    case "health": codeEnd(); codeCard("code-mobile-card--assistant cs-health", codeHealth(ev.data || {})); break;
    case "notice": codeEnd(); codeCard(`cs-notice cs-notice--${esc(ev.level || "info")}`, esc(ev.text)); break;
    case "error":
      codeEnd();
      codeCard("cs-notice cs-notice--error", esc(ev.text));
      code.turnFromVoice = false;
      if (!replay && typeof RayFace !== "undefined" && !TTSController.speaking) RayFace.end(false);
      break;
    case "stats": codeEnd(); codeCard("cs-stats", `${ev.tokens} tokens · ${ev.seconds}s · ${ev.rate} t/s`); break;
    case "approval_request": codeEnd(); codeApprovalCard(ev); break;
    case "approval_resolved": codeResolve(ev.id, ev.ok); break;
    case "cleared":
      codeFeed().innerHTML = "";
      codeEnd();
      code.turnFromVoice = false;
      if (!replay) { codeThinkClosed.clear(); codeSaveThinkState(); }   // a live /clear, not one in the history
      break;
    case "turn_end":
      codeEnd();
      codeOnTurnEnd();
      break;
    case "state": codeSetState(ev); break;
    case "restored": codeRestored(ev); break;
    case "rewound":                                  // the prompt you went back from, back in your input box
      if (!replay && ev.origin === code.client && ev.cmd !== "/edit" && $("code-mobile-input")) {
        const ta = $("code-mobile-input");
        ta.value = ev.text || "";
        ta.dispatchEvent(new Event("input"));
        ta.focus();
      }
      break;
  }
}

// /resume: the saved conversation replaces the feed, drawn like the history on attach
function codeRestored(ev) {
  code.replaying = true;
  code.turnFromVoice = false;
  codeFeed().innerHTML = "";
  codeEnd();
  code.approvals = {};
  codeThinkClosed.clear(); codeSaveThinkState();
  for (const e of ev.events || []) codeEvent(e, true);
  codeRenderCur();
  codeScroll(true);
  code.replaying = false;
  if ($("sessions-drawer")?.dataset.open === "true") sessionsLoad();
}

function codeHello(h) {
  code.replaying = true;
  code.turnFromVoice = false;
  code.client = h.client || "";
  codeFeed().innerHTML = "";
  codeEnd();
  code.approvals = {};
  const events = h.events || [];
  if (!events.length) {
    codeFeed().innerHTML = `<div class="code-mobile-welcome"><div class="code-mobile-welcome-icon">✦</div>
      <div class="code-mobile-welcome-title">CLI session</div>
      <div class="code-mobile-welcome-sub">Ask for a change, or <b>/plan</b> one first. The terminal joins this same session with <code>dl_cli.py --attach</code>.</div></div>`;
  }
  for (const ev of events) codeEvent(ev, true);
  for (const p of (h.state || {}).pending || []) if (!code.approvals[p.id]) codeApprovalCard(p);
  codeRenderCur();
  codeSetState(h.state);
  codeScroll(true);
  code.replaying = false;
}

async function codeConnect() {
  if (code.conn) return;
  const ctl = new AbortController();
  code.conn = ctl;
  code.stale = false;
  let dog = null;
  try {
    const r = await fetch(`api/code/session/events?session=${CODE_SESSION}`, { headers: headers(), signal: ctl.signal });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.error?.message || `HTTP ${r.status}`);
    }
    code.retry = 0;
    code.lastData = Date.now();
    // A stream can die without an error (the phone slept, Wi-Fi or the tunnel dropped): the page then showed nothing
    // more - Clear and Stop seemed to do nothing until a tab switch reconnected.  The server pings every 15 s, so 40 s
    // of silence is a dead stream; an op (Clear, Stop, a prompt) that brought no event in 5 s is one too.
    dog = setInterval(() => {
      const now = Date.now();
      if (now - code.lastData > 40000 || (code.opAt > code.lastData && now - code.opAt > 5000)) {
        code.stale = true;
        ctl.abort();
      }
    }, 2000);
    const reader = r.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      code.lastData = Date.now();
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const block = buf.slice(0, i);
        buf = buf.slice(i + 2);
        const data = block.split("\n").filter((l) => l.startsWith("data: ")).map((l) => l.slice(6)).join("\n");
        if (!data) continue;
        let ev;
        try { ev = JSON.parse(data); } catch (e) { continue; }
        if (ev.type === "hello") codeHello(ev); else codeEvent(ev, false);
      }
    }
  } catch (e) {
    if (e.name !== "AbortError" && code.retry === 0) toast("warn", "CLI session", e.message || String(e), 5000);
  } finally {
    if (dog) clearInterval(dog);
    code.conn = null;
  }
  if (shown("code") && code.stale) {                       // a dead stream: reconnect now, the hello redraws the feed
    code.stale = false;
    code.opAt = 0;
    setTimeout(codeConnect, 0);
  } else if (shown("code") && !ctl.signal.aborted) {      // reconnect: the daemon or the tunnel went away
    code.retry = Math.min(code.retry + 1, 6);
    setTimeout(codeConnect, 500 * 2 ** code.retry);
  }
}

document.addEventListener("visibilitychange", () => {     // back to the page after a while: check the stream first
  if (!document.hidden && shown("code") && code.conn && Date.now() - (code.lastData || 0) > 20000) {
    code.stale = true;
    code.conn.abort();
  }
});

codeFeed()?.addEventListener("toggle", (e) => {
  const d = e.target;
  if (d.tagName !== "DETAILS" || !d.classList.contains("cs-think")) return;
  const block = Number(d.closest(".cs-reply")?.dataset.block);
  if (Number.isNaN(block)) return;
  if (d.open) codeThinkClosed.delete(block); else codeThinkClosed.add(block);
  codeSaveThinkState();
}, true);

function codeDisconnect() { if (code.conn) code.conn.abort(); code.conn = null; }

async function codeOp(op, extra = {}) {
  if (op !== "export" && op !== "archives") code.opAt = Date.now();   // the watchdog expects an event back (codeConnect)
  try {
    const r = await fetch("api/code/session", {
      method: "POST", headers: headers(true),
      body: JSON.stringify({ op, session: CODE_SESSION, origin: code.client, ...extra }),
    });
    const res = await r.json().catch(() => ({}));
    if (!r.ok || res.type === "error") throw new Error(res.error?.message || res.text || `HTTP ${r.status}`);
    return res;
  } catch (e) {
    toast("error", "CLI session", e.message || String(e));
    return null;
  }
}

async function codeSend(text) {
  if (typeof STTController !== "undefined") {
    STTController.cancelAutoSendTimer();
  }
  const ta = $("code-mobile-input");
  text = (text ?? (ta ? ta.value : "")).trim();
  if (!text) return;

  if (typeof TTSController !== "undefined" && TTSController.speaking) {
    TTSController.stop();
  }

  let fromVoice = false;
  if (STTController.lastInputWasVoice && STTController.lastTranscribedText) {
    const spokenLower = STTController.lastTranscribedText.toLowerCase();
    const textLower = text.toLowerCase();
    if (textLower.includes(spokenLower) || spokenLower.includes(textLower)) {
      fromVoice = true;
    }
  }
  code.turnFromVoice = fromVoice;
  STTController.lastInputWasVoice = false;
  STTController.lastTranscribedText = "";

  if (text === "/speak") {
    if (ta && ta.value.trim() === text) { ta.value = ""; ta.style.height = "auto"; }
    const cards = codeFeed() ? codeFeed().querySelectorAll(".code-mobile-card--assistant") : [];
    if (cards.length) {
      const lastCard = cards[cards.length - 1];
      const textEl = lastCard.querySelector(".cs-text") || lastCard.querySelector(".code-mobile-card-body");
      const sp = lastCard.querySelector("[data-code-speak]") || $("code-speak-btn");
      if (textEl) TTSController.speakText(textEl.innerText || textEl.textContent, sp);
    } else {
      toast("info", "No messages yet", "There is no assistant reply to speak.");
    }
    return;
  }
  // spoken prompt: answered in plain speech (voice: true); thinking level is selected automatically (/effort auto)
  const turn = fromVoice ? { text, voice: true } : { text };
  if (await codeOp("input", turn)) {
    if (ta && ta.value.trim() === text) { ta.value = ""; ta.style.height = "auto"; }
    // the answer will be read aloud: the thinking circle shows until then
    if (fromVoice && TTSController.isAutoSpeak() && TTSController.orb()) RayFace.thinking();
  }
}

function openCodeSession() { setScaffoldUI(); codeConnect(); }

function setScaffoldUI() {
  if ($("code-scaffold-title")) $("code-scaffold-title").textContent = "CLI";
}

if ($("code-restart-btn")) {
  $("code-restart-btn").onclick = () => codeSend("/new");     // the current conversation goes to Sessions first
}
if ($("code-stop-btn")) {
  $("code-stop-btn").onclick = () => {
    if (typeof TTSController !== "undefined") TTSController.stop();
    if (typeof RayFace !== "undefined") RayFace.end(false);
    code.turnFromVoice = false;
    codeOp("interrupt");
  };
}
if ($("code-speak-btn")) {
  $("code-speak-btn").onclick = () => {
    const cards = codeFeed() ? codeFeed().querySelectorAll(".code-mobile-card--assistant") : [];
    if (cards.length) {
      const lastCard = cards[cards.length - 1];
      const textEl = lastCard.querySelector(".cs-text") || lastCard.querySelector(".code-mobile-card-body");
      const sp = lastCard.querySelector("[data-code-speak]") || $("code-speak-btn");
      if (textEl) TTSController.speakText(textEl.innerText || textEl.textContent, sp);
    } else {
      toast("info", "No messages yet", "There is no assistant reply to speak.");
    }
  };
}
if ($("code-export-btn")) {
  $("code-export-btn").onclick = async () => {
    const res = await codeOp("export");
    if (!res) return;
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([res.markdown || ""], { type: "text/markdown" }));
    a.download = res.filename || "dl-ai-code-chat.md";
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
    toast("success", "Chat saved", a.download);
  };
}
// ------------------------------------------------------------------ saved sessions (dl_sessiond: /sessions)
// /clear and New keep the conversation they end; this drawer lists them, searches their titles and messages, and
// resumes, renames or deletes one. Resume goes through the session like the typed /resume, so every client follows.
let sessionsTimer = null;
function openSessions(open) {
  const d = $("sessions-drawer");
  if (!d) return;
  if (!open && d.contains(document.activeElement)) {        // focus leaves before the drawer is hidden from AT
    document.activeElement.blur();
    try { ($("code-mobile-input") || $("code-sessions-btn")).focus(); } catch (_) {}
  }
  d.dataset.open = String(open);
  d.toggleAttribute("inert", !open);
  d.inert = !open;
  if (open) { d.removeAttribute("aria-hidden"); sessionsLoad(); setTimeout(() => $("sessions-search")?.focus(), 50); }
  else d.setAttribute("aria-hidden", "true");
  $("scrim").hidden = !open;
}
async function sessionsLoad() {
  const q = ($("sessions-search")?.value || "").trim();
  const res = await codeOp("archives", { query: q });
  if (!res) return;
  const cur = res.current || {};
  $("sessions-current").innerHTML = `<div class="sess-item sess-item--current">
      <div class="sess-main"><div class="sess-title">${esc(cur.title || "(nothing asked yet)")}</div>
        <div class="sess-meta">Now open${cur.id ? " · resumed" : ""}</div></div>
      <div class="sess-actions"><button type="button" class="st-btn st-btn--icon st-btn--sm" data-sess-rename-current title="Rename this conversation" aria-label="Rename this conversation">✎</button></div></div>`;
  const items = res.items || [];
  $("sessions-list").innerHTML = items.length ? items.map((m) => {
    const when = m.updated ? new Date(m.updated * 1000).toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) : "";
    const ws = (m.workspace || "").split("/").slice(-2).join("/");
    return `<div class="sess-item" data-sess-id="${esc(m.id)}">
      <button type="button" class="sess-main" data-sess-resume title="Resume this conversation">
        <span class="sess-title">${m.n}. ${esc(m.title || "(untitled)")}</span>
        <span class="sess-meta">${m.turns || 0} prompts · ${esc(when)} · ${esc(ws)}</span>
        ${m.snippet ? `<span class="sess-snippet">${esc(m.snippet)}</span>` : ""}</button>
      <div class="sess-actions">
        <button type="button" class="st-btn st-btn--icon st-btn--sm" data-sess-rename title="Rename" aria-label="Rename">✎</button>
        <button type="button" class="st-btn st-btn--icon st-btn--sm" data-sess-delete title="Delete" aria-label="Delete">${icon("trash")}</button>
      </div></div>`;
  }).join("") : `<p class="muted small">${q ? "Nothing matches." : "No saved conversations yet. New (or /clear) keeps the current one here."}</p>`;
}
if ($("sessions-drawer")) {
  $("code-sessions-btn").onclick = () => openSessions(true);
  $("sessions-close").onclick = () => openSessions(false);
  $("scrim").addEventListener("click", () => openSessions(false));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && $("sessions-drawer").dataset.open === "true") openSessions(false); });
  $("sessions-search").addEventListener("input", () => { clearTimeout(sessionsTimer); sessionsTimer = setTimeout(sessionsLoad, 250); });
  $("sessions-new").onclick = () => { codeSend("/new"); openSessions(false); };
  $("sessions-drawer").addEventListener("click", async (e) => {
    const item = e.target.closest("[data-sess-id]");
    if (e.target.closest("[data-sess-rename-current]")) {
      const t = prompt("Name this conversation:", code.state.title || "");
      if (t && t.trim()) { await codeSend(`/rename ${t.trim()}`); setTimeout(sessionsLoad, 400); }
      return;
    }
    if (!item) return;
    const id = item.dataset.sessId, title = item.querySelector(".sess-title")?.textContent.replace(/^\d+\.\s*/, "") || "";
    if (e.target.closest("[data-sess-resume]")) {
      if (code.state.busy) { toast("warn", "Sessions", "The session is working: stop it or wait, then resume."); return; }
      codeSend(`/resume ${id}`);
      openSessions(false);
    } else if (e.target.closest("[data-sess-rename]")) {
      const t = prompt("Rename this saved conversation:", title);
      if (t && t.trim() && await codeOp("archive_rename", { id, title: t.trim() })) sessionsLoad();
    } else if (e.target.closest("[data-sess-delete]")) {
      if (confirm(`Delete "${title}" from the saved list?`) && await codeOp("archive_delete", { id })) sessionsLoad();
    }
  });
}
if ($("code-fullscreen-btn")) {
  $("code-fullscreen-btn").onclick = () => document.querySelector(".code-terminal-wrap")?.classList.toggle("code-terminal--fullscreen");
}
if (codeFeed()) {
  codeFeed().addEventListener("click", (e) => {
    const sp = e.target.closest("[data-code-speak]");
    if (sp) {
      const card = sp.closest(".code-mobile-card");
      const textEl = card.querySelector(".cs-text") || card.querySelector(".code-mobile-card-body");
      if (textEl) TTSController.speakText(textEl.innerText || textEl.textContent, sp);
      return;
    }
    const pa = e.target.closest("[data-prompt-edit],[data-prompt-rewind],[data-prompt-branch],[data-prompt-send],[data-prompt-send-branch],[data-prompt-cancel]");
    if (pa) { codePromptAction(pa); return; }
    const cp = e.target.closest("[data-code-copy]");
    if (cp) {
      const card = cp.closest(".code-mobile-card");
      const textEl = card.querySelector(".cs-text") || card.querySelector(".code-mobile-card-body");
      if (textEl) copyText(textEl.innerText || textEl.textContent, cp);
      return;
    }
  });
}
// A past prompt: edit it in place and run it again (/edit), rewind to before it (/rewind), or branch from before it
// (/branch: the whole conversation stays in Sessions). The daemon cuts the conversation and every client redraws it.
function codePromptAction(btn) {
  const card = btn.closest(".code-mobile-card--user");
  if (!card) return;
  const ref = `@${card.dataset.seq}`, body = card.querySelector(".code-mobile-card-body");
  if (btn.matches("[data-prompt-cancel]")) { body.textContent = card.dataset.prompt; card.classList.remove("cs-editing"); return; }
  if (code.state.busy) { toast("warn", "CLI session", "The session is working: stop it or wait first."); return; }
  if (btn.matches("[data-prompt-edit]")) {
    if (card.classList.contains("cs-editing")) return;
    card.classList.add("cs-editing");
    body.innerHTML = `<textarea class="cs-edit-input" rows="3" aria-label="Edited prompt"></textarea>
      <div class="cs-edit-actions">
        <button type="button" class="st-btn st-btn--primary st-btn--sm" data-prompt-send title="Replace this prompt and run it; what came after it is removed">Send</button>
        <button type="button" class="st-btn st-btn--secondary st-btn--sm" data-prompt-send-branch title="Keep the whole conversation in Sessions and run the edited prompt in a branch">Send as branch</button>
        <button type="button" class="st-btn st-btn--secondary st-btn--sm" data-prompt-cancel>Cancel</button></div>`;
    const ta = body.querySelector("textarea");
    ta.value = card.dataset.prompt;
    ta.style.height = Math.min(ta.scrollHeight + 4, 240) + "px";
    ta.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); body.querySelector("[data-prompt-send]").click(); }
      if (e.key === "Escape") { e.stopPropagation(); body.querySelector("[data-prompt-cancel]").click(); }
    });
    ta.focus();
    return;
  }
  if (btn.matches("[data-prompt-send],[data-prompt-send-branch]")) {
    const text = (body.querySelector("textarea")?.value || "").trim();
    if (!text) return;
    codeSend(`${btn.matches("[data-prompt-send]") ? "/edit" : "/branch"} ${ref} ${text}`);
    return;
  }
  if (btn.matches("[data-prompt-rewind]")) {
    if (confirm("Rewind to before this prompt? It and everything after it are removed (Branch keeps them).")) codeSend(`/rewind ${ref}`);
    return;
  }
  if (btn.matches("[data-prompt-branch]")) codeSend(`/branch ${ref}`);
}
if ($("code-mobile-send-btn")) $("code-mobile-send-btn").onclick = () => codeSend();
if ($("code-mobile-input")) {
  $("code-mobile-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); codeSend(); }
  });
  $("code-mobile-input").addEventListener("input", function (e) {
    this.style.height = "auto";
    this.style.height = Math.min(this.scrollHeight, 160) + "px";
    if (e.isTrusted && !STTController.isRecording) {
      if (!this.value.trim()) {
        STTController.lastInputWasVoice = false;
        STTController.lastTranscribedText = "";
      }
    }
  });
  // Screenshot and file pasting directly into chat/code input (#3748, #3838)
  $("code-mobile-input").addEventListener("paste", async (e) => {
    const dt = e.clipboardData;
    if (!dt) return;
    const files = [];
    for (const f of Array.from(dt.files || [])) {
      if (f.type.startsWith("image/") || /\.pdf$/i.test(f.name)) files.push(f);
    }
    // Screenshots on clipboard (Win+Shift+S / Spectacle) often arrive in items rather than files
    if (!files.some(f => f.type.startsWith("image/"))) {
      for (const item of Array.from(dt.items || [])) {
        if (item.kind === "file" && item.type.startsWith("image/")) {
          const file = item.getAsFile();
          if (file) {
            const ext = file.type.split("/")[1]?.replace("jpeg", "jpg").replace(/[+].*/, "") || "png";
            const now = new Date();
            const pad = (n) => String(n).padStart(2, "0");
            const stamp = `${now.getFullYear()}${pad(now.getMonth()+1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
            const name = `pasted-image-${stamp}${files.length ? `-${files.length + 1}` : ""}.${ext}`;
            files.push(new File([file], name, { type: file.type }));
          }
        }
      }
    }
    if (files.length) {
      e.preventDefault();
      await uploadFilesToWorkspace(files);
      const input = $("code-mobile-input");
      const refs = files.map(f => `@${f.name}`).join(" ");
      input.value = input.value ? `${input.value.trimEnd()} ${refs} ` : `${refs} `;
      input.focus();
      input.dispatchEvent(new Event("input"));
      toast("success", "File attached", files.map(f => f.name).join(", "), 3000);
    }
  });
}
document.querySelectorAll(".code-mobile-chip").forEach((chip) => {
  chip.onclick = () => {
    const cmd = chip.dataset.cmd;
    if ("run" in chip.dataset) { codeSend(cmd); return; }
    const input = $("code-mobile-input");
    input.value = cmd + " ";
    input.focus();
  };
});
document.addEventListener("visibilitychange", () => {     // phones suspend background tabs: reconnect on return
  if (document.visibilityState === "visible" && shown("code") && !code.conn) codeConnect();
});

// ------------------------------------------------------------------ server access
const DEFAULT_KEY = "";
function headers(json = false) {
  const h = {};
  const key = store.get("apikey", DEFAULT_KEY);
  if (key) h.Authorization = "Bearer " + key;
  if (json) h["Content-Type"] = "application/json";
  return h;
}
$("api-key").value = store.get("apikey", DEFAULT_KEY);
// D.L. AI: behind Cloudflare Access the login is the credential - no key is kept or sent from this browser
(async () => {
  try {
    const r = await fetch("api/whoami", { headers: headers() });
    const who = r.ok ? await r.json() : null;
    if (who && who.auth === "cf-access") {
      store.set("apikey", "");
      const field = $("api-key").closest(".st-field");
      if (field) field.innerHTML = `<span class="st-label">Signed in with Cloudflare Access <output>${(who.email || "").replace(/[<>&"]/g, "")}</output></span>`;
    }
  } catch (e) { /* older server or offline: keep the key field */ }
})();
$("api-key").onchange = () => { store.set("apikey", $("api-key").value.trim()); toast("success", "API key saved", "Kept in this browser only."); };

if ($("force-restart-btn")) {
  $("force-restart-btn").onclick = async () => {
    if (!confirm("Forcefully kill the running engine process and restart/reset?")) return;
    const btn = $("force-restart-btn");
    btn.disabled = true;
    btn.textContent = "Restarting…";
    try {
      const r = await fetch("restart", {method: "POST", headers: headers(true), body: "{}"});
      if (!r.ok) {
        let msg = `HTTP ${r.status}`;
        try { msg = (await r.json()).error.message || msg; } catch (e) {}
        throw new Error(msg);
      }
      const res = await r.json();
      toast("success", "Engine restarted", `Model state: ${res.status || "ready"}`);
    } catch (e) {
      toast("error", "Restart failed", e.message || String(e), 6000);
    } finally {
      btn.disabled = false;
      btn.textContent = "Force Restart";
    }
  };
}

if ($("logout-btn")) {
  $("logout-btn").onclick = () => {
    if (!confirm("Are you sure you want to log out?")) return;
    try {
      localStorage.clear();
      sessionStorage.clear();
    } catch (e) {}
    const host = window.location.hostname;
    const domains = [host, "." + host, ""];
    const cookieNames = ["CF_Authorization", "CF_AppSession", "CF_Session", "strata.apikey", "strata.theme"];
    try {
      document.cookie.split(";").forEach(c => {
        const name = c.split("=")[0].trim();
        if (name && !cookieNames.includes(name)) cookieNames.push(name);
      });
    } catch (e) {}
    for (const d of domains) {
      for (const name of cookieNames) {
        document.cookie = `${name}=; Path=/; ${d ? `Domain=${d}; ` : ""}Expires=Thu, 01 Jan 1970 00:00:01 GMT; Max-Age=0;`;
      }
    }
    // Cloudflare Access keeps two sessions: this app's CF_Authorization cookie (HttpOnly, so only Cloudflare's own
    // logout page can clear it) and the session on the team domain, which silently signs the app in again on the next
    // visit. So: end the app's cookie in the background, then open the team logout (site-config.js sets its URL).
    const appLogout = "/cdn-cgi/access/logout";
    const teamLogout = window.STRATA_LOGOUT_URL || "";
    const go = (url) => {
      try { (window.top || window).location.href = url; } catch (e) { window.location.href = url; }
    };
    if (!teamLogout || teamLogout === appLogout) { go(appLogout); return; }
    let left = false;
    const leave = () => { if (!left) { left = true; go(teamLogout); } };
    setTimeout(leave, 3000);                  // never wait longer than this for the app logout
    fetch(appLogout, { credentials: "include", cache: "no-store", redirect: "manual" })
      .catch(() => {})
      .finally(leave);
  };
}

async function loadAvailableModels() {
  if (!$("model-select")) return;
  try {
    const r = await fetch("available_models", {headers: headers()});
    if (r.ok) {
      const data = await r.json();
      if (data.models && data.models.length) {
        $("model-select").innerHTML = data.models.map(m =>
          `<option value="${esc(m.id)}"${m.active ? " selected" : ""}>${esc(m.name || m.id)}</option>`
        ).join("");
      }
    }
  } catch (e) {}
}

if ($("model-select")) {
  $("model-select").onchange = async () => {
    const target = $("model-select").value;
    toast("info", "Switching model…", `Selecting ${target}`);
    try {
      const r = await fetch("switch_model", {
        method: "POST",
        headers: headers(true),
        body: JSON.stringify({model: target})
      });
      if (!r.ok) {
        let msg = `HTTP ${r.status}`;
        try { msg = (await r.json()).error.message || msg; } catch (e) {}
        throw new Error(msg);
      }
      const res = await r.json();
      if (res.status === "already_loaded") {
        toast("info", "Already Active", `${res.name || target} is already loaded.`);
      } else {
        toast("success", "Model Active", `${res.name || target} (${res.status || "ready"}).`);
      }
      loadHealth();
    } catch (e) {
      toast("error", "Model Switch Failed", e.message || String(e), 6000);
      loadAvailableModels();
    }
  };
}

let health = {model: "Ray", images: false, max_context: 0};
async function loadHealth() {
  try {
    health = await (await fetch("health")).json();
    if ($("model-select") && health.model) {
      $("model-select").value = health.model;
    }
  } catch (e) {
    setTimeout(loadHealth, 2000);
  }
}

// ------------------------------------------------------------------ Monitor
const METRICS = [
  {key: "speed", label: "Speed", icon: "gauge", unit: "t/s", series: "tok_s"},
  {key: "gpu", label: "GPU load", icon: "gpu", unit: "%", series: "gpu_util", max: 100},
  {key: "vram", label: "VRAM", icon: "layers", unit: "GB", series: "gpu_mem_used"},
  {key: "temp", label: "GPU temp", icon: "thermometer", unit: "°C", series: "gpu_temp", tone: "warn"},
  {key: "power", label: "Power", icon: "bolt", unit: "W", series: "gpu_power"},
  {key: "cpu", label: "CPU", icon: "cpu", unit: "%", series: "cpu", max: 100},
  {key: "ram", label: "System RAM", icon: "memory", unit: "GB", series: "ram_used"},
  {key: "disk", label: "Disk read", icon: "disk", unit: "MB/s", series: "disk_read_mb", tone: "info"},
];
$("metrics").innerHTML = METRICS.map((m) => `
  <div class="st-card metric-card"><div class="st-metric">
    <span class="st-metric__label">${icon(m.icon, "st-icon st-icon--sm")}${esc(m.label)}</span>
    ${m.key === "speed" ? `<div class="speed-values">
      <div><span class="st-metric__value" id="mv-speed">-</span><span class="st-metric__sub" id="ms-speed">Decode</span></div>
      <div class="speed-prefill"><span class="st-metric__value" id="mv-prefill">-</span><span class="st-metric__sub" id="ms-prefill">Prefill</span></div>
    </div>` : `<span class="st-metric__value" id="mv-${m.key}">–</span>
    <span class="st-metric__sub" id="ms-${m.key}"></span>`}
    <svg class="st-metric__spark" id="sp-${m.key}" viewBox="0 0 100 32" preserveAspectRatio="none"${m.tone ? ` data-tone="${m.tone}"` : ""}>
      <path class="area" fill="currentColor" opacity=".12"/><path class="line" fill="none" stroke="currentColor"
      stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/>
      ${m.key === "speed" ? `<g id="sp-prefill" class="speed-prefill"><path class="area" fill="currentColor" opacity=".12"/>
        <path class="line" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"
        stroke-linecap="round" vector-effect="non-scaling-stroke"/></g>` : ""}</svg>
  </div></div>`).join("");

function spark(id, values, max) {
  const svg = $(id);
  const v = (values || []).map((x) => (x == null ? 0 : x));
  if (v.length < 2) { svg.querySelector(".line").setAttribute("d", ""); svg.querySelector(".area").setAttribute("d", ""); return; }
  const top = Math.max(max || 0, ...v, 1);
  const pts = v.map((x, i) => [(i / (v.length - 1)) * 100, 30 - (x / top) * 26]);
  const line = pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(2)},${p[1].toFixed(2)}`).join("");
  svg.querySelector(".line").setAttribute("d", line);
  svg.querySelector(".area").setAttribute("d", `${line}L100,32L0,32Z`);
}
function setMetric(key, value, unit, sub) {
  $(`mv-${key}`).innerHTML = value == null ? "–" : `${esc(value)}${unit ? `<small>${esc(unit)}</small>` : ""}`;
  $(`ms-${key}`).textContent = sub || "";
}

let lastMetrics = null, metricsFailures = 0, keyWarned = false, mcpTick = 0;
let reqShowAll = false;   // the Monitor's request table: the last 12, or every one the server keeps (issue #35)
async function poll() {
  try {
    const r = await fetch(reqShowAll ? "metrics?requests=all" : "metrics", {headers: headers()});
    if (r.status === 401) {
      setPill("error", "API key needed");
      if (!keyWarned) { keyWarned = true; toast("warn", "API key needed", "This server needs a key: add it under About > Settings.", 6000); }
    } else if (r.ok) {
      lastMetrics = await r.json();
      metricsFailures = 0;
      render(lastMetrics);
    } else {
      throw new Error(`HTTP ${r.status}`);
    }
  } catch (e) {
    if (++metricsFailures === 3) setPill("error", "Server not reachable");
  }
  if (shown("monitor") && ++mcpTick % 10 === 0) loadMcp();       // server states change rarely: every 10 s
  setTimeout(poll, 1000);
}

function setPill(state, text) {
  $("pill").dataset.state = state === "error" ? "queued" : state;
  $("pill-text").textContent = text;
}

function render(m) {
  const live = m.live || {}, hw = m.hardware || {}, st = m.hardware_static || {}, eng = m.engine || {}, h = m.history || {};
  const last = (m.requests || [])[0];
  // the header pill
  if (live.state === "reading") {
    const pct = live.prompt_total ? Math.round((100 * live.prompt_read) / live.prompt_total) : null;
    setPill("reading", pct != null ? `Reading prompt · ${pct}%` : "Reading prompt");
  } else if (live.state === "generating") {
    setPill("generating", `Generating · ${fmt(live.tok_s, 1)} tok/s`);
  } else {
    setPill("idle", "Idle");
  }
  if (live.queued > 0) setPill("queued", `${live.queued} queued`);
  if (shown("monitor")) renderMonitor(live, hw, st, eng, h, last, m.requests || [], m.totals, m.requests_kept);
  if (shown("monitor")) renderConvCache(m.conversation_cache);
  if (shown("about")) renderAbout(eng, hw, st);
}

// #596: the conversation cache - the prompt's state the engine keeps between requests (always), and the whole
// conversations it parks in RAM when "--conversation-cache-mib N" is in the run config's args (opt-in)
function since(t) {
  if (!t) return "";
  const s = Math.max(0, Date.now() / 1000 - t);
  return s < 60 ? "just now" : s < 3600 ? `${fmt(s / 60)} min ago` : `${fmt(s / 3600, 1)} h ago`;
}
function renderConvCache(c) {
  $("cc-card").hidden = !c;
  if (!c) return;                                  // an older server
  const pct = (a, b) => (b ? `${Math.min(100, (100 * a) / b)}%` : "0%");
  $("cc-bars").hidden = !c.enabled;
  if (c.enabled) {
    $("cc-slots-text").textContent = `${fmt(c.parked)} / ${fmt(c.slots)}`;
    $("cc-slots-bar").style.width = pct(c.parked, c.slots);
    const budget = c.budget_mib * 1048576;
    $("cc-mem-text").textContent = `${gb(c.bytes)} / ${gb(budget)} GB`;
    $("cc-mem-bar").style.width = pct(c.bytes, budget);
  }
  $("cc-sum").textContent = c.requests ? `${fmt(c.requests_reused)} of ${fmt(c.requests)} requests reused part of their prompt` : "";
  const share = c.prompt_tokens ? ` (${fmt((100 * c.reused_tokens) / c.prompt_tokens)}% of all prompt tokens)` : "";
  const event = c.last_event ? `${c.last_event === "parked" ? "Parked" : "Restored"} ${fmt(c.last_tokens)} tokens, ${since(c.last_at)}` : null;
  facts($("cc-facts"), [
    ["Last request", c.last_prompt != null ? `${fmt(c.last_reused || 0)} of ${fmt(c.last_prompt)} prompt tokens reused` : null],
    ["Reused since start", c.requests ? `${fmt(c.reused_tokens)} tokens${share}` : null],
    ["Parked / restored", c.enabled ? `${fmt(c.parks)} / ${fmt(c.restores)}${c.evictions ? ` · ${fmt(c.evictions)} evicted` : ""}` : null],
    ["Last switch", c.enabled ? event : null],
  ]);
  $("cc-note").textContent = c.enabled
    ? "A request that continues a parked conversation gets its state back instead of reading it again; the oldest goes when the slots or the memory are full."
    : "The engine keeps the last conversation's state, so a follow-up reads only what is new. To keep several conversations (agents taking turns), add \"--conversation-cache-mib\", \"8192\" to the run config's args (docs/DETAILS.md).";
}

function renderTotals(t) {
  if (!t || !t.requests) return "";
  const since = new Date(t.since * 1000).toLocaleString([], {weekday: "short", hour: "2-digit", minute: "2-digit"});
  const read = t.prompt_tokens - t.reused;
  const pSpeed = t.prompt_ms > 0 && read > 0 ? ` at ${fmt(read / (t.prompt_ms / 1000))} tok/s` : "";
  const oSpeed = t.decode_ms > 0 && t.output_tokens > 0 ? ` at ${fmt(t.output_tokens / (t.decode_ms / 1000), 1)} tok/s` : "";
  return `Since ${since}: ${fmt(t.requests)} requests · ${fmt(read)} prompt tokens read${pSpeed} (${fmt(t.reused)} reused) · ` +
         `${fmt(t.output_tokens)} written${oSpeed}`;
}
function renderMonitor(live, hw, st, eng, h, last, requests, totals, kept) {
  // model state
  const on = live.queued > 0 ? "queued" : live.state;
  for (const b of document.querySelectorAll("#state-badges .st-badge")) b.classList.toggle("on", b.dataset.s === on || b.dataset.s === live.state);
  const prog = $("state-progress");
  let label = "Waiting for a request", detail = "", pct = 0;
  if (live.state === "reading") {
    label = "Reading prompt";
    prog.dataset.tone = "info";
    if (live.prompt_total) {
      pct = (100 * live.prompt_read) / live.prompt_total;
      detail = `${fmt(live.prompt_read)} / ${fmt(live.prompt_total)} tokens · ${fmt(pct)}%`;
    } else {
      detail = `${fmt(live.prompt_tokens)} tokens`;
    }
  } else if (live.state === "generating") {
    label = live.phase ? live.phase[0].toUpperCase() + live.phase.slice(1) : "Generating";
    delete prog.dataset.tone;
    pct = live.max_tokens ? Math.min(100, (100 * live.generated) / live.max_tokens) : 0;
    detail = `${fmt(live.generated)} tokens · ${fmt(live.tok_s, 1)} tok/s`;
  } else if (last) {
    delete prog.dataset.tone;
    detail = `last: ${fmt(last.output_tokens)} tokens${last.decode_tok_s ? ` at ${fmt(last.decode_tok_s, 1)} tok/s` : ""}`;
  }
  $("state-label").textContent = label;
  $("state-detail").textContent = detail;
  $("state-bar").style.width = `${pct}%`;

  // the eight cards
  const speed = live.state === "generating" ? live.tok_s : last ? last.decode_tok_s : null;
  setMetric("speed", speed == null ? null : fmt(speed, 1), "t/s",
            live.state === "generating" ? "Decode now" : last ? "Decode last request" : "Decode");
  const prefill = live.state !== "idle" ? live.prefill_tok_s_mean
                : last && last.prompt_ms > 0 ? Math.max(0, last.prompt_tokens - (last.reused || 0)) / (last.prompt_ms / 1000) : null;
  setMetric("prefill", prefill == null ? null : fmt(prefill), "t/s",
            live.state === "reading" ? "Prefill now" : live.state === "generating" ? "Prefill this request" : last ? "Prefill last request" : "Prefill");
  spark("sp-speed", h.tok_s);
  spark("sp-prefill", h.prefill_tok_s_mean);
  // a model split across several cards (issue #112): the cards show their total / mean / hottest, and each card's own
  const per = (f) => (hw.gpus || []).map((g) => `GPU ${g.index} ${f(g)}`).join(" · ");
  const multi = (hw.gpus || []).length > 1;
  setMetric("gpu", hw.gpu_util == null ? null : fmt(hw.gpu_util), "%",
            multi ? per((g) => (g.util == null ? "–" : `${fmt(g.util)}%`)) : st.gpu_name || (st.gpu_note ? "not available" : ""));
  spark("sp-gpu", h.gpu_util, 100);
  const isLoaded = live.state !== "unloaded";
  setMetric("vram", hw.gpu_mem_used == null ? null : gb(hw.gpu_mem_used), hw.gpu_mem_total ? `/ ${gb(hw.gpu_mem_total, 0)} GB` : "GB",
            multi ? per((g) => (g.mem_used == null ? "–" : `${gb(g.mem_used)} GB`))
                  : (isLoaded && eng.expert_slots ? `${fmt(eng.expert_slots)} experts cached` : (st.gpu_note ? "not available on Windows AMD yet" : "")));
  spark("sp-vram", h.gpu_mem_used, hw.gpu_mem_total);
  setMetric("temp", hw.gpu_temp == null ? null : fmt(hw.gpu_temp), "°C",
            multi ? per((g) => (g.temp == null ? "–" : `${fmt(g.temp)}°`)) : "");
  spark("sp-temp", h.gpu_temp, 90);
  setMetric("power", hw.gpu_power == null ? null : fmt(hw.gpu_power), "W", hw.gpu_power_limit ? `of ${fmt(hw.gpu_power_limit)} W limit` : "");
  spark("sp-power", h.gpu_power, hw.gpu_power_limit);
  setMetric("cpu", hw.cpu == null ? null : fmt(hw.cpu), "%", st.threads ? `${st.cores ? `${st.cores} cores · ` : ""}${st.threads} threads` : "");
  spark("sp-cpu", h.cpu, 100);
  const ramUsedPct = hw.ram_total ? Math.round((100 * hw.ram_used) / hw.ram_total) : null;
  const ramFree = hw.ram_total && hw.ram_used != null ? gb(hw.ram_total - hw.ram_used, 1) : null;
  setMetric("ram", hw.ram_used == null ? null : gb(hw.ram_used), hw.ram_total ? `/ ${gb(hw.ram_total, 0)} GB` : "GB",
            ramUsedPct != null ? `${ramUsedPct}% in use · ${ramFree} GB free` : "");
  spark("sp-ram", h.ram_used, hw.ram_total);
  if (hw.disk_read_mb == null) {
    setMetric("disk", null, "", st.psutil ? "" : "needs psutil (setup installs it)");
  } else {
    const big = hw.disk_read_mb >= 1000;
    setMetric("disk", big ? fmt(hw.disk_read_mb / 1024, 2) : fmt(hw.disk_read_mb, hw.disk_read_mb < 10 ? 1 : 0), big ? "GB/s" : "MB/s",
              hw.disk_write_mb == null ? "" : `write ${fmt(hw.disk_write_mb, 1)} MB/s`);
  }
  spark("sp-disk", h.disk_read_mb);

  // context fill: the running request, else the last one
  const ctx = eng.max_context || 0;
  let used = 0;
  if (live.state !== "idle" && isLoaded) used = (live.prompt_tokens || 0) + (live.generated || 0);
  else if (last && isLoaded) used = (last.prompt_tokens || 0) + (last.output_tokens || 0);
  const frac = ctx && isLoaded ? Math.min(1, used / ctx) : 0;
  $("ctx-fill").setAttribute("stroke-dasharray", `${(235.6 * frac).toFixed(1)} 314.2`);
  $("ctx-fill").style.opacity = 235.6 * frac >= 3 ? "1" : "0";         // a near-zero arc would draw just its round cap
  $("ctx-pct").textContent = isLoaded ? `${Math.round(frac * 100)}%` : "0%";
  $("ctx-sub").textContent = isLoaded && ctx ? `${kfmt(used)} / ${ctxfmt(ctx)}` : "–";
  const cacheBytes = (eng.expert_cache_mib || 0) * 1048576;
  $("slots-text").textContent = isLoaded && eng.expert_slots ? `${fmt(eng.expert_slots)} · ${gb(cacheBytes)} GB` : "–";
  $("slots-bar").style.width = isLoaded && hw.gpu_mem_total ? `${Math.min(100, (100 * cacheBytes) / hw.gpu_mem_total)}%` : "0%";
  const arenaBytes = (eng.arena_mib || 0) * 1048576;
  $("ram-text").textContent = isLoaded && eng.arena_mib ? `${gb(arenaBytes)} / ${gb(hw.ram_total, 0)} GB` : (isLoaded && eng.expert_slots ? "0 GB" : "–");
  const arenaPct = isLoaded && hw.ram_total && eng.arena_mib ? Math.min(100, (100 * arenaBytes) / hw.ram_total) : 0;
  $("ram-bar").style.width = `${arenaPct}%`;
  const kvBpt = {k8v4: 9792, int8: 12672, q4_0: 6912, fp16: 24576}[eng.kv] || 9792;
  const kvMaxBytes = ctx * kvBpt;
  const kvUsedBytes = used * kvBpt;
  const kvMemFmt = (b) => {
    if (b == null || b <= 0) return "0 MB";
    if (b >= 1073741824) return `${fmt(b / 1073741824, 1)} GB`;
    return `${fmt(b / 1048576, b < 10485760 ? 1 : 0)} MB`;
  };
  const kvPct = ctx ? Math.min(100, (100 * used) / ctx) : 0;
  if ($("kv-text")) {
    $("kv-text").textContent = isLoaded && ctx ? `${kvMemFmt(kvUsedBytes)} / ${kvMemFmt(kvMaxBytes)}${eng.kv ? ` · ${eng.kv.toUpperCase()}` : ""}` : "–";
  }
  if ($("kv-bar")) {
    $("kv-bar").style.width = isLoaded ? `${kvPct}%` : "0%";
  }
  if ($("kv-progress")) {
    if (kvPct > 90) $("kv-progress").dataset.tone = "danger";
    else if (kvPct > 75) $("kv-progress").dataset.tone = "warn";
    else delete $("kv-progress").dataset.tone;
  }

  // recent requests
  const body = $("req-body");
  if (!requests.length) {
    body.innerHTML = `<tr><td colspan="9" class="muted">No requests yet</td></tr>`;
  } else {
    const badge = {stop: ["", "Done"], length: ["", "Max tokens"], cancel: ["st-badge--queued", "Stopped"],
                   disconnect: ["st-badge--queued", "Closed"], error: ["st-badge--error", "Error"]};
    body.innerHTML = requests.slice(0, reqShowAll ? requests.length : 12).map((r) => {
      const [cls, text] = badge[r.finish] || ["", r.finish || "–"];
      const t = new Date(r.time * 1000).toLocaleTimeString([], {hour: "2-digit", minute: "2-digit", second: "2-digit"});
      const proj = r.projection == null ? "" : ` <span class="st-badge${r.projection ? " st-badge--reading" : ""}" title="experimental speed projection ${r.projection ? "on" : "off"}">${r.projection ? "ESP" : "stock"}</span>`;
      // #588: the VRAM share; the PCIe share (--pcie-frac) beside it when there is one
      const hit = r.hit_rate == null ? "–" : `${(r.hit_rate * 100).toFixed(1)}%` +
        (r.pcie_share ? ` <span class="muted" title="routed experts the GPU read over PCIe (--pcie-frac) or another GPU computed">+${(r.pcie_share * 100).toFixed(1)}% PCIe</span>` : "");
      // Reused tokens are not prefetched again. Match the Monitor's existing Prefill metric.
      const fresh = r.prompt_tokens == null ? null : Math.max(0, r.prompt_tokens - (r.reused || 0));
      const prefillRate = fresh > 0 && r.prompt_ms > 0 ? fresh / (r.prompt_ms / 1000) : null;
      return `<tr><td>${esc(t)}</td><td><span class="st-badge ${cls}">${esc(text)}</span>${proj}</td><td class="num">${fmt(r.prompt_tokens)}</td>
        <td class="num">${fmt(r.reused)}</td><td class="num">${fmt(r.output_tokens)}</td><td class="num">${fmt(prefillRate)}</td><td class="num">${fmt(r.decode_tok_s, 1)}</td>
        <td class="num">${hit}</td><td class="num">${fmt(r.duration_s, 1)} s</td></tr>`;
    }).join("");
  }
  const all = $("req-all");
  kept = kept == null ? requests.length : kept;
  all.hidden = kept <= 12;
  all.textContent = reqShowAll ? "Show fewer" : `Show all (${kept})`;
  $("req-wrap").classList.toggle("all", reqShowAll);
  $("req-totals").textContent = renderTotals(totals);
}

function facts(el, rows) {
  el.innerHTML = rows.filter((r) => r[1] != null && r[1] !== "").map(([k, v, copy]) =>
    `<dt>${esc(k)}</dt><dd>${copy ? `<code>${esc(v)}</code><button class="st-btn st-btn--icon" data-copy="${esc(v)}" aria-label="Copy">${icon("copy")}</button>` : esc(v)}</dd>`).join("");
}
// INFO cvec=project:4-44[:singleL] | add:A-B | 0
function projectionText(c) {
  if (!c || c === "0" || c === 0) return null;
  const [mode, range, single] = String(c).split(":");
  const [a, b] = (range || "").split("-");
  return `${mode === "project" ? "Projection" : "Additive"} control vector on layers ${a}–${b}` +
         `${single ? ` (layer ${single.replace("single", "")}'s direction)` : ""}. Per chat in Sampling. Its package ` +
         "describes the vector as a refusal-direction projection; measure the speed yourself";
}
function renderAbout(eng, hw, st) {
  const kv = {int8: "8-bit", q4_0: "4-bit (Hadamard-rotated)", fp16: "16-bit"}[eng.kv] || eng.kv;
  facts($("facts-engine"), [
    ["Model", eng.model],
    ["Engine", eng.version ? `v${eng.version}` : "built from source"],
    ["Context", eng.max_context ? `${fmt(eng.max_context)} tokens` : null],
    ["KV cache", kv ? `${kv}${eng.kv_resident ? `, streamed: ${fmt(eng.kv_resident)} positions per layer in VRAM, the rest in RAM` : ", all in VRAM"}` : null],
    ["Experts in VRAM", eng.expert_slots ? `${fmt(eng.expert_slots)} (${gb((eng.expert_cache_mib || 0) * 1048576)} GB)` : null],
    ["Speculation", eng.spec ? `MTP drafts up to ${Math.max(0, (eng.mtp_max || eng.spec) - 1)} tokens${eng.lookup ? ", prompt lookup on" : ""}` : null],
    ["Images", eng.images ? "on" : "off"],
    ["Experimental speed projection", projectionText(eng.cvec)],
  ]);
  facts($("facts-hw"), [
    ["GPU", st.gpu_name ? `${st.gpu_name}${hw.gpu_mem_total ? `, ${gb(hw.gpu_mem_total, 0)} GB` : ""}` : (st.gpu_note || "not readable (NVML)")],
    ["CPU", st.cpu_name ? `${st.cpu_name}${st.threads ? `, ${st.threads} threads` : ""}` : null],
    ["RAM", hw.ram_total ? `${gb(hw.ram_total, 0)} GB` : null],
  ]);
  const base = location.origin;
  facts($("facts-api"), [
    ["OpenAI base URL", `${base}/v1`, true],
    ["Anthropic base URL", base, true],
    ["Model name", eng.model, true],
  ]);
}
document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-copy]");
  if (b) copyText(b.dataset.copy, b);
});
$("req-all").addEventListener("click", () => { reqShowAll = !reqShowAll; if (lastMetrics) render(lastMetrics); });

// ------------------------------------------------------------------ MCP servers (GET /mcp)
// Tools from the MCP servers in the run config: the chat offers them to the model (opt-in per request,
// "strata_mcp": true, which only this page sends); the Monitor lists the servers and what they offer.
let mcpInfo = {servers: [], tools: 0}, mcpRetry = null;
async function loadMcp() {
  try {
    const r = await fetch("mcp", {headers: headers()});
    if (!r.ok) return;
    mcpInfo = await r.json();
  } catch (e) { return; /* an older server: no MCP */ }
  renderMcp();
  clearTimeout(mcpRetry);                          // right after the start, servers may still be starting (npx downloads)
  if ((mcpInfo.servers || []).some((s) => s.status === "starting")) mcpRetry = setTimeout(loadMcp, 3000);
}
const MCP_STATE = {ready: ["st-badge--generating", "Connected"], starting: ["st-badge--reading", "Starting"],
                   failed: ["st-badge--error", "Failed"], stopped: ["st-badge--queued", "Stopped"], idle: ["", "Waiting"]};
function renderMcp() {
  const servers = mcpInfo.servers || [];
  $("mcp-card").hidden = !servers.length;
  const ready = servers.filter((s) => s.status === "ready" || s.status === "stopped");
  $("mcp-sum").textContent = servers.length ? `${fmt(mcpInfo.tools)} tools · ${ready.length} of ${servers.length} servers connected` : "";
  $("mcp-list").innerHTML = servers.map((s) => {
    const [cls, text] = MCP_STATE[s.status] || ["", s.status];
    const info = s.info && s.info.name ? ` · ${s.info.name}${s.info.version ? ` ${s.info.version}` : ""}` : "";
    return `<div class="mcp-server"><div class="mcp-server__head"><span class="st-badge ${cls}">${esc(text)}</span>` +
      `<strong>${esc(s.name)}</strong><span class="muted small">${esc(s.transport)} · ${fmt(s.tools.length)} tools${esc(info)}</span></div>` +
      (s.error ? `<div class="msg-error">${esc(s.error)}</div>` : "") +
      (s.tools.length ? `<div class="mcp-server__tools">${s.tools.map((t) => `<span class="chip" title="${esc(t.description || "")}">${esc(t.tool)}</span>`).join("")}</div>` : "") +
      `</div>`;
  }).join("");
}

// ------------------------------------------------------------------ Model settings (GET / POST /config, #564)
// A few documented keys of the run config (strata-<model>.json), for every client, from the next start on.  The
// server lists them, checks every value and keeps every other key of the file as it is.
let cfgKeys = [];
async function loadConfig() {
  let r;
  try { r = await fetch("config", {headers: headers()}); } catch (e) { return; }
  if (!r.ok) { $("cfg-card").hidden = true; return; }       // no run config, an older server, or no key yet
  const c = await r.json();
  cfgKeys = c.keys || [];
  $("cfg-file").textContent = c.file || "";
  $("cfg-form").innerHTML = cfgKeys.map((k, i) => {
    const id = `cfg-${i}`, v = k.value;
    let input;
    if (k.kind === "bool" || k.kind === "enum") {
      const opts = k.kind === "bool" ? [["true", "on"], ["false", "off"]] : k.choices.map((x) => [x, x]);
      const cur = v == null ? "" : String(v);
      input = `<select class="st-input" id="${id}"><option value=""${cur === "" ? " selected" : ""}>default</option>` +
        opts.map(([val, text]) => `<option value="${esc(val)}"${cur === val ? " selected" : ""}>${esc(text)}</option>`).join("") + `</select>`;
    } else {
      const text = v == null ? "" : Array.isArray(v) ? v.join(", ") : String(v);
      input = `<input class="st-input" id="${id}" ${k.kind === "number" ? 'type="number" step="any" min="0"' : 'type="text"'} ` +
        `value="${esc(text)}" placeholder="default" autocomplete="off">`;
    }
    return `<label for="${id}" title="${esc(k.help)}">${esc(k.help)}<code>${esc(k.key)}</code></label>${input}`;
  }).join("");
  $("cfg-card").hidden = false;
}
function configValue(k, el) {
  const s = el.value.trim();
  if (s === "") return null;
  if (k.kind === "bool") return s === "true";
  if (k.kind === "number") return Number(s);
  return s;                                         // enum, or names (the server splits them at commas)
}
$("cfg-save").addEventListener("click", async () => {
  const set = {};
  cfgKeys.forEach((k, i) => {
    const v = configValue(k, $(`cfg-${i}`));
    const old = Array.isArray(k.value) ? k.value.join(", ") : k.value;
    if (JSON.stringify(v) !== JSON.stringify(old ?? null)) set[k.key] = v;
  });
  if (!Object.keys(set).length) { $("cfg-msg").textContent = "Nothing changed."; return; }
  try {
    const r = await fetch("config", {method: "POST", headers: headers(true), body: JSON.stringify({set})});
    const b = await r.json();
    if (!r.ok) throw new Error((b.error || {}).message || `HTTP ${r.status}`);
    $("cfg-msg").textContent = b.changed.length
      ? `Saved (${b.changed.join(", ")}); the earlier file is ${b.file}.bak. Start the model again to use it.` : "Nothing changed.";
    loadConfig();
  } catch (e) {
    $("cfg-msg").textContent = "";
    toast("error", "Not saved", String(e.message || e), 6000);
  }
});

// ------------------------------------------------------------------ Markdown (escaped first, then formatted)
function inline(s) {
  const codes = [];
  s = s.replace(/`([^`\n]+)`/g, (_, c) => { codes.push(c); return `\u0000${codes.length - 1}\u0000`; });
  s = esc(s)
    .replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*\w])\*([^*\n]+)\*(?![*\w])/g, "$1<em>$2</em>")
    .replace(/\[([^\]\n]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  return s.replace(/\u0000(\d+)\u0000/g, (_, i) => `<code class="inline">${esc(codes[+i])}</code>`);
}
function codeBlock(lang, code) {
  return `<div class="st-code"><div class="st-code__head"><span>${esc(lang || "code")}</span>` +
    `<button class="st-btn st-btn--icon" data-code-copy aria-label="Copy code">${icon("copy")}</button></div>` +
    `<pre><code>${esc(code)}</code></pre></div>`;
}
function blocks(text) {
  const out = [], lines = text.split("\n");
  let para = [], list = null;
  const flushPara = () => {
    if (!para.length) return;
    // CommonMark / GFM soft breaks: single newlines become spaces; two spaces or backslash at line end produce hard breaks (#3818)
    const parts = [];
    for (let p = 0; p < para.length; p++) {
      const line = para[p];
      const hard = /( {2,}|\\)$/.test(line);
      parts.push(inline(line.replace(/( {2,}|\\)$/, "")));
      if (p < para.length - 1) parts.push(hard ? "<br>" : " ");
    }
    out.push(`<p>${parts.join("")}</p>`);
    para = [];
  };
  const flushList = () => { if (list) out.push(`<${list.tag}>${list.items.map((i) => `<li>${inline(i)}</li>`).join("")}</${list.tag}>`); list = null; };
  for (let i = 0; i < lines.length; i++) {
    const l = lines[i];
    let m;
    if (!l.trim()) { flushPara(); flushList(); continue; }
    if ((m = l.match(/^(#{1,6})\s+(.*)$/))) { flushPara(); flushList(); out.push(`<${m[1].length <= 2 ? "h3" : "h4"}>${inline(m[2])}</${m[1].length <= 2 ? "h3" : "h4"}>`); continue; }
    if (/^\s*([-*_])\s*\1\s*\1[\s\1]*$/.test(l)) { flushPara(); flushList(); out.push("<hr>"); continue; }
    if ((m = l.match(/^>\s?(.*)$/))) { flushPara(); flushList(); out.push(`<blockquote>${inline(m[1])}</blockquote>`); continue; }
    if (/^\s*\|.*\|\s*$/.test(l) && i + 1 < lines.length && /^\s*\|?[\s:-]+\|[\s|:-]*$/.test(lines[i + 1])) {
      flushPara(); flushList();
      const cells = (row) => row.trim().replace(/^\||\|$/g, "").split("|").map((c) => inline(c.trim()));
      let html = `<table><thead><tr>${cells(l).map((c) => `<th>${c}</th>`).join("")}</tr></thead><tbody>`;
      i += 2;
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) html += `<tr>${cells(lines[i++]).map((c) => `<td>${c}</td>`).join("")}</tr>`;
      i--;
      out.push(html + "</tbody></table>");
      continue;
    }
    if ((m = l.match(/^\s*(?:[-*+]|(\d+)[.)])\s+(.*)$/))) {
      flushPara();
      const tag = m[1] ? "ol" : "ul";
      if (!list || list.tag !== tag) { flushList(); list = {tag, items: []}; }
      list.items.push(m[2]);
      continue;
    }
    if (list && /^\s{2,}\S/.test(l)) { list.items[list.items.length - 1] += " " + l.trim(); continue; }
    flushList();
    para.push(l);
  }
  flushPara(); flushList();
  return out.join("");
}
function markdown(text) {
  let html = "", rest = text;
  for (;;) {
    const m = rest.match(/(^|\n)```([^\n`]*)\n/);
    if (!m) { html += blocks(rest); break; }
    html += blocks(rest.slice(0, m.index));
    rest = rest.slice(m.index + m[0].length);
    const end = rest.match(/(^|\n)```[ \t]*(\n|$)/);
    if (!end) { html += codeBlock(m[2].trim(), rest); break; }         // still streaming
    html += codeBlock(m[2].trim(), rest.slice(0, end.index));
    rest = rest.slice(end.index + end[0].length);
  }
  return html;
}

// ------------------------------------------------------------------ settings (thinking and sampling, shared with the CLI)
const DEFAULTS = {thinking: "auto", temperature: 0.6, top_p: 0.95, top_k: 20, max: "", seed: "", esp: true};
let settings = {...DEFAULTS, ...store.get("sampling", {})};

// ------------------------------------------------------------------ the sampling drawer
let lastDrawerTrigger = null;
function openDrawer(open) {
  const drawer = $("drawer");
  if (!drawer) return;
  if (open) {
    if (document.activeElement && (document.activeElement.id === "sampling-btn" || document.activeElement.id === "code-sampling-btn")) {
      lastDrawerTrigger = document.activeElement;
    }
    drawer.dataset.open = "true";
    drawer.removeAttribute("aria-hidden");
    drawer.removeAttribute("inert");
    drawer.inert = false;
    $("scrim").hidden = false;
    loadDrawer();
    syncShared().then(loadDrawer);
    loadMcp();
  } else {
    // Release focus from any focused element inside drawer before setting aria-hidden/inert
    if (document.activeElement && drawer.contains(document.activeElement)) {
      document.activeElement.blur();
      if (lastDrawerTrigger && typeof lastDrawerTrigger.focus === "function") {
        try { lastDrawerTrigger.focus(); } catch (_) {}
      } else if (shown("code") && $("code-mobile-input")) {
        try { $("code-mobile-input").focus(); } catch (_) {}
      }
    }
    drawer.dataset.open = "false";
    drawer.setAttribute("aria-hidden", "true");
    drawer.setAttribute("inert", "");
    drawer.inert = true;
    $("scrim").hidden = true;
  }
}
function loadDrawer(s = settings) {
  const eff = (code.state && code.state.effort) || s.thinking || "auto";
  for (const b of $("s-thinking").children) b.setAttribute("aria-checked", String(b.dataset.v === eff));
  $("s-temp").value = s.temperature; $("s-topp").value = s.top_p; $("s-topk").value = s.top_k;
  $("s-max").value = s.max; $("s-seed").value = s.seed;
  $("s-esp").setAttribute("aria-checked", String(s.esp !== false));
  $("esp-row").hidden = !projectionLoaded();
  outputs();
}
// D.L. AI: the Chat settings live on the server (GET/POST /settings), so every browser and the CLI (Code tab, terminal),
// which sends no sampling fields of its own, use the same ones.  The server's copy wins; with none yet, this browser's
// settings are published.
function fromShared(d) {
  const stored = store.get("sampling", {});
  return {thinking: stored.thinking || (d.reasoning_effort === "high" ? "auto" : d.reasoning_effort) || DEFAULTS.thinking,
          temperature: d.temperature ?? DEFAULTS.temperature,
          top_p: d.top_p ?? settings.top_p, top_k: d.top_k ?? settings.top_k,
          max: d.max_tokens ? String(d.max_tokens) : "", seed: d.seed != null ? String(d.seed) : "",
          esp: d.experimental_speed_projection ?? settings.esp};
}
async function syncShared() {
  try {
    const r = await fetch("settings", {headers: headers()});
    if (!r.ok) return;                                   // no key yet, or an older server
    const j = await r.json();
    if (j.shared && j.defaults) {
      settings = {...settings, ...fromShared(j.defaults)};
      store.set("sampling", settings);
    } else {
      await saveShared(settings);
    }
  } catch (e) { /* offline: keep this browser's copy */ }
}
function sharedDefaults(s) {
  const d = {reasoning_effort: (s.thinking && s.thinking !== "auto") ? s.thinking : "high", temperature: +s.temperature};
  if (+s.temperature > 0) Object.assign(d, {top_p: +s.top_p, top_k: +s.top_k});
  if (s.seed) d.seed = +s.seed;
  if (s.max) d.max_tokens = +s.max;
  if (projectionLoaded()) d.experimental_speed_projection = s.esp !== false;
  return d;
}
async function saveShared(s) {
  const r = await fetch("settings", {method: "POST", headers: headers(true),
                                      body: JSON.stringify({defaults: sharedDefaults(s)})});
  if (!r.ok) {
    let msg = `HTTP ${r.status}`;
    try { msg = (await r.json()).error.message || msg; } catch (e) { /* not json */ }
    throw new Error(msg);
  }
}
// the engine was started with the experimental-speed-projection control vector (INFO cvec=...)
function projectionLoaded() {
  const c = lastMetrics && lastMetrics.engine ? lastMetrics.engine.cvec : 0;
  return !!c && c !== "0";
}
function outputs() {
  const t = +$("s-temp").value;
  $("o-temp").textContent = t === 0 ? "0 · greedy" : t.toFixed(2);
  $("o-topp").textContent = (+$("s-topp").value).toFixed(2);
  $("o-topk").textContent = $("s-topk").value;
  const sel = [...$("s-thinking").children].find((b) => b.getAttribute("aria-checked") === "true");
  $("o-thinking").textContent = sel ? {auto: "auto per turn (default)", none: "answers right away", low: "short", medium: "medium", high: "thorough"}[sel.dataset.v] : "";
  for (const id of ["s-topp", "s-topk"]) $(id).disabled = t === 0;
}
for (const b of $("s-thinking").children) b.onclick = () => { for (const x of $("s-thinking").children) x.setAttribute("aria-checked", String(x === b)); outputs(); };
for (const id of ["s-temp", "s-topp", "s-topk"]) $(id).oninput = outputs;
$("s-esp").onclick = () => $("s-esp").setAttribute("aria-checked", String($("s-esp").getAttribute("aria-checked") !== "true"));
// the recommended coding-agent settings (DEFAULTS), applied and saved for Chat and the CLI at once
$("s-reset").onclick = () => { loadDrawer(DEFAULTS); $("s-apply").click(); };
$("s-apply").onclick = async () => {
  const sel = [...$("s-thinking").children].find((b) => b.getAttribute("aria-checked") === "true");
  const thinking = sel ? sel.dataset.v : "auto";
  settings = {thinking, temperature: +$("s-temp").value, top_p: +$("s-topp").value,
              top_k: +$("s-topk").value, max: $("s-max").value.trim(), seed: $("s-seed").value.trim(),
              esp: $("s-esp").getAttribute("aria-checked") === "true"};
  store.set("sampling", settings);
  openDrawer(false);
  try {
    await saveShared(settings);
  } catch (e) {
    toast("error", "Saved here, but not on the server", `The CLI keeps the previous settings: ${e.message}`, 6000);
    return;
  }
  try {
    await codeOp("input", { text: `/effort ${thinking}` });
  } catch (_) {}
  toast("success", "Sampling saved", (settings.temperature === 0 ? "Greedy: the same question gives the same answer. " : "") +
        `Thinking set to ${thinking}.`);
};
// ------------------------------------------------------------------ Server Workspace
let wsFiles = [];
let wsRoot = "";                      // the server's workspace folder, for @path references
let wsLoading = false;

function openWorkspace(open = true) {
  const dlg = $("workspace-dialog");
  if (!dlg) return;
  if (open) {
    if (typeof dlg.showModal === "function") {
      try { dlg.showModal(); } catch (e) { dlg.setAttribute("open", ""); }
    } else {
      dlg.setAttribute("open", "");
    }
    loadWorkspaceFiles();
  } else {
    if (typeof dlg.close === "function") dlg.close();
    else dlg.removeAttribute("open");
  }
}

async function loadWorkspaceFiles() {
  if (wsLoading) return;
  wsLoading = true;
  const list = $("ws-file-list");
  if (list) list.innerHTML = `<tr><td colspan="4" class="muted">Loading workspace files&hellip;</td></tr>`;
  try {
    const r = await fetch("api/workspace/files", { headers: headers() });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const data = await r.json();
    wsFiles = data.files || [];
    wsRoot = data.workspace || "";
    if (data.workspace && $("ws-path")) $("ws-path").textContent = data.workspace;
    renderWorkspaceFiles();
  } catch (err) {
    if (list) list.innerHTML = `<tr><td colspan="4" class="muted">Failed to load workspace files: ${esc(err.message)}</td></tr>`;
    toast("error", "Workspace error", err.message);
  } finally {
    wsLoading = false;
  }
}

const wsExpandedFolders = new Set();

function fmtWsSize(b) {
  if (b == null || isNaN(b)) return "–";
  if (b > 1048576) return `${(b / 1048576).toFixed(1)} MB`;
  if (b > 1024) return `${(b / 1024).toFixed(0)} KB`;
  return `${b} B`;
}

function buildWorkspaceTree(items, query = "") {
  const root = {
    name: "",
    path: "",
    is_dir: true,
    folders: new Map(),
    files: [],
    totalFiles: 0,
    totalSize: 0,
    hasMatches: false
  };

  function getOrCreateFolder(segments) {
    let curr = root;
    let currPath = "";
    for (const seg of segments) {
      currPath = currPath ? `${currPath}/${seg}` : seg;
      if (!curr.folders.has(seg)) {
        curr.folders.set(seg, {
          name: seg,
          path: currPath,
          is_dir: true,
          folders: new Map(),
          files: [],
          totalFiles: 0,
          totalSize: 0,
          hasMatches: false
        });
      }
      curr = curr.folders.get(seg);
    }
    return curr;
  }

  // Ensure explicit directories are registered
  for (const item of items) {
    if (item.is_dir) {
      const parts = item.path.split("/").filter(Boolean);
      getOrCreateFolder(parts);
    }
  }

  // Place files into folders
  for (const item of items) {
    if (item.is_dir) continue;
    const parts = item.path.split("/").filter(Boolean);
    const fileName = parts.pop() || item.name;
    const parentFolder = parts.length > 0 ? getOrCreateFolder(parts) : root;

    const isMatch = !query || item.name.toLowerCase().includes(query) || item.path.toLowerCase().includes(query);
    if (isMatch) {
      parentFolder.files.push({
        ...item,
        name: fileName
      });
    }
  }

  // Compute recursive totals
  function computeTotals(node) {
    let count = node.files.length;
    let size = node.files.reduce((sum, f) => sum + (f.size || 0), 0);
    let matched = node.files.length > 0;

    for (const child of node.folders.values()) {
      computeTotals(child);
      count += child.totalFiles;
      size += child.totalSize;
      if (child.hasMatches || child.totalFiles > 0) {
        matched = true;
      }
    }

    node.totalFiles = count;
    node.totalSize = size;
    node.hasMatches = matched;
  }

  computeTotals(root);
  return root;
}

function renderFolderNode(folder, depth, list, query) {
  if (query && !folder.hasMatches && folder.totalFiles === 0) return;

  const isExpanded = wsExpandedFolders.has(folder.path) || Boolean(query);
  const tr = document.createElement("tr");
  tr.className = `ws-folder-row ${depth > 0 ? "ws-folder-row--nested" : ""}`;
  tr.dataset.expanded = String(isExpanded);
  tr.dataset.path = folder.path;

  const indentPx = 12 + depth * 18;

  tr.innerHTML = `
    <td class="ws-file-name-cell" style="padding-left: ${indentPx}px;">
      <span class="ws-folder-chevron">${isExpanded ? "▼" : "▶"}</span>
      <span class="ws-file-icon">${icon("folder", "st-icon st-icon--sm")}</span>
      <strong class="ws-file-title" title="${esc(folder.path)}">${esc(folder.name)}/</strong>
      <span class="ws-folder-badge">${folder.totalFiles} item${folder.totalFiles === 1 ? "" : "s"}</span>
    </td>
    <td class="num muted small">${fmtWsSize(folder.totalSize)}</td>
    <td class="muted small">–</td>
    <td class="num ws-actions-cell">
      <button type="button" class="st-btn st-btn--icon ws-action-btn ws-del-btn" title="Delete folder">
        ${icon("trash", "st-icon st-icon--sm")}
      </button>
    </td>
  `;

  tr.querySelector("td").onclick = () => {
    if (wsExpandedFolders.has(folder.path)) {
      wsExpandedFolders.delete(folder.path);
    } else {
      wsExpandedFolders.add(folder.path);
    }
    renderWorkspaceFiles();
  };

  tr.querySelector(".ws-del-btn").onclick = (e) => {
    e.stopPropagation();
    deleteFromWorkspace({ name: folder.name, path: folder.path, is_dir: true });
  };

  list.appendChild(tr);

  if (isExpanded) {
    const subfolders = Array.from(folder.folders.values()).sort((a, b) => a.name.localeCompare(b.name));
    for (const sub of subfolders) {
      renderFolderNode(sub, depth + 1, list, query);
    }

    const files = folder.files.slice().sort((a, b) => a.name.localeCompare(b.name));
    for (const file of files) {
      renderFileRow(file, depth + 1, list);
    }
  }
}

function renderFileRow(f, depth, list) {
  const tr = document.createElement("tr");
  if (depth > 0) tr.className = "ws-child-row";

  const indentPx = 12 + depth * 18 + (depth > 0 ? 18 : 0);

  const tdName = document.createElement("td");
  tdName.className = "ws-file-name-cell";
  tdName.style.paddingLeft = `${indentPx}px`;

  const fileIcon = f.kind === "image" ? "image" : "attach";
  tdName.innerHTML = `
    <span class="ws-file-icon">${icon(fileIcon, "st-icon st-icon--sm")}</span>
    <span class="ws-file-title" title="${esc(f.path)}">${esc(f.name)}</span>
  `;
  tr.appendChild(tdName);

  const tdSize = document.createElement("td");
  tdSize.className = "num muted small";
  tdSize.textContent = fmtWsSize(f.size);
  tr.appendChild(tdSize);

  const tdDate = document.createElement("td");
  tdDate.className = "muted small";
  const d = new Date(f.mtime * 1000);
  tdDate.textContent = `${d.toLocaleDateString()} ${d.toLocaleTimeString([], {hour: "2-digit", minute:"2-digit"})}`;
  tr.appendChild(tdDate);

  const tdActions = document.createElement("td");
  tdActions.className = "num ws-actions-cell";

  const btnAttach = document.createElement("button");
  btnAttach.type = "button";
  btnAttach.className = "st-btn st-btn--secondary st-btn--sm ws-action-btn";
  btnAttach.title = "Attach this file to chat prompt";
  btnAttach.innerHTML = `${icon("attach", "st-icon st-icon--sm")}<span>Attach</span>`;
  btnAttach.onclick = () => attachFromWorkspace(f);
  tdActions.appendChild(btnAttach);

  const btnDown = document.createElement("button");
  btnDown.type = "button";
  btnDown.className = "st-btn st-btn--icon ws-action-btn";
  btnDown.title = "Download to browser";
  btnDown.innerHTML = icon("download", "st-icon st-icon--sm");
  btnDown.onclick = () => downloadFromWorkspace(f);
  tdActions.appendChild(btnDown);

  const btnDel = document.createElement("button");
  btnDel.type = "button";
  btnDel.className = "st-btn st-btn--icon ws-action-btn ws-del-btn";
  btnDel.title = "Delete from workspace";
  btnDel.innerHTML = icon("trash", "st-icon st-icon--sm");
  btnDel.onclick = () => deleteFromWorkspace(f);
  tdActions.appendChild(btnDel);

  tr.appendChild(tdActions);
  list.appendChild(tr);
}

function renderWorkspaceFiles() {
  const list = $("ws-file-list");
  if (!list) return;
  const query = ($("ws-search") ? $("ws-search").value : "").trim().toLowerCase();

  const tree = buildWorkspaceTree(wsFiles, query);

  const allFileCount = wsFiles.filter(f => !f.is_dir).length;
  if ($("ws-count")) {
    $("ws-count").textContent = `${tree.totalFiles} of ${allFileCount} file${allFileCount === 1 ? "" : "s"}`;
  }

  if (tree.totalFiles === 0 && tree.folders.size === 0) {
    list.innerHTML = `<tr><td colspan="4" class="muted">${query ? "No matching files" : "Workspace is empty. Drop files or folders above to upload."}</td></tr>`;
    return;
  }

  list.innerHTML = "";

  // Render top-level folders
  const topFolders = Array.from(tree.folders.values()).sort((a, b) => a.name.localeCompare(b.name));
  for (const folder of topFolders) {
    renderFolderNode(folder, 0, list, query);
  }

  // Render root-level files
  const rootFiles = tree.files.slice().sort((a, b) => a.name.localeCompare(b.name));
  for (const file of rootFiles) {
    renderFileRow(file, 0, list);
  }
}

// "Attach" puts an @path reference in the Code prompt; D.L. CLI reads the file into the prompt (@file references)
function attachFromWorkspace(f) {
  const ref = `@${wsRoot ? `${wsRoot}/` : ""}${f.path}`;
  if (!/^@[A-Za-z0-9_\-./]+$/.test(ref)) {
    toast("warn", "Cannot attach this file", "An @file reference cannot hold spaces or special characters: rename it first.");
    return;
  }
  const ta = $("code-mobile-input");
  ta.value = `${ta.value.replace(/\s*$/, "")}${ta.value.trim() ? " " : ""}${ref} `;
  openWorkspace(false);
  ta.focus();
  toast("success", "Added to the prompt", f.name);
}

async function downloadFromWorkspace(f) {
  try {
    // a single-use link the browser's own download manager fetches: streamed straight to disk, with progress and
    // resume, instead of holding the whole file in page memory (large zips failed on mobile)
    const r = await fetch("api/workspace/download-ticket", {
      method: "POST", headers: headers(true), body: JSON.stringify({ file: f.path }),
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const { url } = await r.json();
    const a = document.createElement("a");
    a.href = url;
    a.download = f.name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    toast("success", "Download started", f.name);
  } catch (err) {
    toast("error", "Download failed", err.message);
  }
}

async function deleteFromWorkspace(f) {
  const targetLabel = f.is_dir ? `folder "${f.name}" and all its contents` : `"${f.name}"`;
  if (!confirm(`Delete ${targetLabel} from server workspace?`)) return;
  try {
    const r = await fetch(`api/workspace/delete?file=${encodeURIComponent(f.path)}`, {
      method: "POST",
      headers: headers(true),
      body: JSON.stringify({ file: f.path })
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    if (f.is_dir) {
      for (const p of Array.from(wsExpandedFolders)) {
        if (p === f.path || p.startsWith(`${f.path}/`)) {
          wsExpandedFolders.delete(p);
        }
      }
    }
    toast("success", "Deleted", f.name);
    loadWorkspaceFiles();
  } catch (err) {
    toast("error", "Delete failed", err.message);
  }
}

async function extractFilesFromDataTransfer(dataTransfer) {
  if (!dataTransfer) return [];
  const items = dataTransfer.items;
  if (!items || !items.length) {
    return [...(dataTransfer.files || [])];
  }

  const files = [];
  async function readEntry(entry, path = "") {
    if (entry.isFile) {
      return new Promise((resolve) => {
        entry.file((f) => {
          f.relativePath = path ? `${path}/${f.name}` : f.name;
          files.push(f);
          resolve();
        }, () => resolve());
      });
    } else if (entry.isDirectory) {
      const dirReader = entry.createReader();
      return new Promise((resolve) => {
        function readBatch() {
          dirReader.readEntries(async (entries) => {
            if (!entries.length) {
              resolve();
              return;
            }
            const nextPath = path ? `${path}/${entry.name}` : entry.name;
            for (const sub of entries) {
              await readEntry(sub, nextPath);
            }
            readBatch();
          }, () => resolve());
        }
        readBatch();
      });
    }
  }

  const promises = [];
  for (let i = 0; i < items.length; i++) {
    const item = items[i];
    if (item.webkitGetAsEntry) {
      const entry = item.webkitGetAsEntry();
      if (entry) promises.push(readEntry(entry));
    } else {
      const f = item.getAsFile();
      if (f) files.push(f);
    }
  }
  await Promise.all(promises);
  return files.length ? files : [...(dataTransfer.files || [])];
}

async function uploadFilesToWorkspace(fileList) {
  if (!fileList || !fileList.length) return;
  let count = 0;
  for (const file of fileList) {
    try {
      const uploadPath = file.relativePath || file.name;
      toast("info", "Uploading…", uploadPath, 1500);
      const r = await fetch(`api/workspace/upload?file=${encodeURIComponent(uploadPath)}`, {
        method: "POST",
        headers: {
          ...headers(),
          "X-Filename": uploadPath,
          "Content-Type": "application/octet-stream"
        },
        body: file
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      count++;
    } catch (err) {
      toast("error", `Failed to upload ${file.name}`, err.message);
    }
  }
  if (count > 0) {
    toast("success", `Uploaded ${count} file${count === 1 ? "" : "s"} to workspace`, "Saved in server workspace");
    loadWorkspaceFiles();
  }
}

if ($("workspace-btn")) $("workspace-btn").onclick = () => openWorkspace(true);
if ($("code-workspace-btn")) $("code-workspace-btn").onclick = () => openWorkspace(true);
if ($("ws-close-btn")) $("ws-close-btn").onclick = () => openWorkspace(false);
if ($("ws-refresh-btn")) $("ws-refresh-btn").onclick = () => loadWorkspaceFiles();
if ($("ws-search")) $("ws-search").oninput = () => renderWorkspaceFiles();
if ($("ws-file-input")) $("ws-file-input").onchange = () => {
  uploadFilesToWorkspace($("ws-file-input").files);
  $("ws-file-input").value = "";
};

const wsDropzone = $("ws-dropzone");
if (wsDropzone) {
  wsDropzone.addEventListener("click", (e) => {
    if (e.target !== $("ws-file-input") && !e.target.closest("label")) {
      $("ws-file-input").click();
    }
  });
  wsDropzone.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      $("ws-file-input").click();
    }
  });
  wsDropzone.addEventListener("dragover", (e) => {
    e.preventDefault();
    wsDropzone.classList.add("ws-dropzone--active");
  });
  wsDropzone.addEventListener("dragleave", () => {
    wsDropzone.classList.remove("ws-dropzone--active");
  });
  wsDropzone.addEventListener("drop", async (e) => {
    e.preventDefault();
    wsDropzone.classList.remove("ws-dropzone--active");
    const files = await extractFilesFromDataTransfer(e.dataTransfer);
    if (files.length) uploadFilesToWorkspace(files);
  });
}

const wsDialog = $("workspace-dialog");
if (wsDialog) {
  wsDialog.addEventListener("dragover", (e) => { e.preventDefault(); });
  wsDialog.addEventListener("drop", async (e) => {
    if (e.target !== wsDropzone && !wsDropzone.contains(e.target)) {
      e.preventDefault();
      const files = await extractFilesFromDataTransfer(e.dataTransfer);
      if (files.length) uploadFilesToWorkspace(files);
    }
  });
  wsDialog.addEventListener("click", (e) => {
    const rect = wsDialog.getBoundingClientRect();
    const isInDialog = (rect.top <= e.clientY && e.clientY <= rect.top + rect.height
      && rect.left <= e.clientX && e.clientX <= rect.left + rect.width);
    if (!isInDialog) openWorkspace(false);
  });
}

// Window-level drop handler: prevents accidental browser file navigation and ingests files (#3838)
window.addEventListener("dragover", (e) => {
  if (Array.from(e.dataTransfer?.types || []).includes("Files")) {
    e.preventDefault();
  }
});
window.addEventListener("drop", async (e) => {
  if (Array.from(e.dataTransfer?.types || []).includes("Files")) {
    if (wsDropzone && (e.target === wsDropzone || wsDropzone.contains(e.target))) return;
    if (wsDialog && (e.target === wsDialog || wsDialog.contains(e.target))) return;
    e.preventDefault();
    const files = await extractFilesFromDataTransfer(e.dataTransfer);
    if (files.length) {
      await uploadFilesToWorkspace(files);
      const input = $("code-mobile-input");
      if (input) {
        const refs = files.map(f => `@${f.name}`).join(" ");
        input.value = input.value ? `${input.value.trimEnd()} ${refs} ` : `${refs} `;
        input.focus();
        input.dispatchEvent(new Event("input"));
      }
      toast("success", "Files added to workspace", files.map(f => f.name).join(", "), 3000);
    }
  }
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    if (typeof STTController !== "undefined") STTController.cancelAutoSendTimer();
    if ($("drawer") && $("drawer").dataset.open === "true") openDrawer(false);
    if ($("workspace-dialog") && ($("workspace-dialog").hasAttribute("open") || $("workspace-dialog").open)) openWorkspace(false);
    if ($("brave-stt-dialog") && ($("brave-stt-dialog").hasAttribute("open") || $("brave-stt-dialog").open)) STTController.closeBraveGuide();
  }
});

if ($("code-sampling-btn")) $("code-sampling-btn").onclick = () => { lastDrawerTrigger = $("code-sampling-btn"); openDrawer(true); };   // the same settings drive the CLI
syncShared();                                            // the server's Chat settings, or publish this browser's
$("drawer-close").onclick = () => openDrawer(false);
$("scrim").onclick = () => openDrawer(false);

// ------------------------------------------------------------------ start
TTSController.init();
STTController.init();
loadHealth().then(loadMcp).then(loadAvailableModels);
showTab(location.hash.slice(1) || "code");
poll();
