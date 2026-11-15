// serve/web/app-02-tts.js - part of the web app (see app-01-util.js): Text-to-Speech (TTS) engine.
// A classic script, loaded in order by index.html; it shares its globals with the others.
"use strict";

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

// male voices by name, for browsers without Piper: Piper's own, Edge/Windows, Chrome desktop, Apple, Android
// ("male" as a word only: "female" must not match)
const RAY_MALE_VOICE = new RegExp("\\bmale\\b|hfc_male|ryan|joe\\b|john\\b|bryce|norman|kusal|mike\\b|sam\\b|" +
  "guy\\b|davis|andrew|brian|christopher|eric\\b|roger|steffan|ryan|william|liam|thomas|daniel|david|mark\\b|" +
  "george|alex\\b|fred\\b|aaron|arthur|oliver|google uk english male", "i");
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

    // 1. Highest priority: Ray's voice (Piper HFC male), then Piper's other male voice (ryan), then any Piper voice
    const piper = voices.find((v) => /hfc_male/i.test(v.name || v.voiceURI)) ||
                  voices.find((v) => /ryan/i.test(v.name || v.voiceURI)) ||
                  voices.find((v) => /piper|lessac/i.test(v.name || v.voiceURI));
    if (piper) return piper;

    // Ray is male (since 2026-10-28): without Piper (a phone, Edge, macOS) each step below takes a male voice of its
    // kind first.  Android Chrome names voices by language only ("English United States", lang en_US): there no name
    // says male, so the local US voice comes first as before
    const us = (v) => /^en[-_]us$/i.test(v.lang || "");
    const male = (list) => list.find((v) => RAY_MALE_VOICE.test(v.name || v.voiceURI)) ||
                           list.find((v) => us(v) && v.localService) || list.find(us) || list[0];

    // 2. High priority: Native neural / natural voices (Edge Natural / Chrome OS Neural / Apple Siri)
    const natural = male(voices.filter((v) => /natural|neural|online/i.test(v.name || v.voiceURI)));
    if (natural) return natural;

    // 3. English non-eSpeak local voice
    const enNonEspeak = male(voices.filter((v) => /^en/i.test(v.lang) && !/espeak/i.test(v.name || v.voiceURI)));
    if (enNonEspeak) return enNonEspeak;

    // 4. Any non-eSpeak local voice
    const anyNonEspeak = male(voices.filter((v) => !/espeak/i.test(v.name || v.voiceURI)));
    if (anyNonEspeak) return anyNonEspeak;

    // 5. System default or first available
    return voices.find((v) => v.default) || voices.find((v) => v.localService) || voices[0] || null;
  },

  getRate() { return +store.get("tts_rate", 1.0); },
  getPitch() { return +store.get("tts_pitch", 1.5); },
  getCodeMode() { return store.get("tts_code_mode", "skip"); },
  // on unless turned off: a spoken prompt is answered aloud (typed ones never are)
  isAutoSpeak() { return store.get("tts_auto_speak", true) !== false; },
  // persistent speaker toggle on the Code tab header: arms TTS for all subsequent requests (typed & spoken)
  isSpeakToggleOn() { return store.get("tts_speak_toggle", false) === true; },
  willAutoSpeak() { return this.isAutoSpeak() || this.isSpeakToggleOn(); },

  updateSpeakToggleBtn(on = this.isSpeakToggleOn()) {
    const btn = $("code-speak-btn");
    if (!btn) return;
    btn.classList.toggle("is-active", on);
    btn.setAttribute("aria-pressed", String(on));
    btn.title = `Speak replies aloud: ${on ? "ON (Click to turn off)" : "OFF (Click to turn on)"}`;
  },

  setSpeakToggle(val) {
    const on = Boolean(val);
    store.set("tts_speak_toggle", on);
    this.updateSpeakToggleBtn(on);
    if (!on && this.speaking) {
      this.stop();
      if (typeof codeSpeechEnd === "function") codeSpeechEnd();
    }
  },
  // on unless turned off in About: Ray the red panda while reading aloud, and his thinking pose (web/rayface.js)
  isOrbOn() { return store.get("tts_orb", true) !== false; },
  // on unless turned off in About: Ray's thinking pose for every turn (typed, spoken or from the terminal), not only
  // for spoken prompts that will be read aloud
  isThinkAllOn() { return store.get("tts_think_all", true) !== false; },
  // a spoken prompt's reply is read sentence by sentence while it is written (web/speakstream.js), not after the turn
  isStreamOn() { return store.get("tts_stream", true) !== false; },
  orb() { return typeof RayFace !== "undefined" && this.isOrbOn() && !(this.activeBtn && this.activeBtn.id === "tts-test-btn"); },
  // Ray's Piper voice made by the server (POST v1/audio/speech): on unless turned off, when the server has it.  The
  // audio plays through Web Audio, so the face's waveform follows the voice; a failure falls back to the browser voice.
  serverTTS: null,
  isServerVoiceOn() { return store.get("tts_server", true) !== false; },
  // in the Android app the voice is played natively (speakNative): a WebView's audio can only use the media volume
  useServer() { return !this.nativeQueue() && this.isServerVoiceOn() && !!(this.serverTTS && this.serverTTS.available) && !this.serverFailed; },
  nativeQueue() { return !!(window.RayAndroid && typeof window.RayAndroid.speakQueued === "function"); },

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
      if (!this.speaking || this.paused || this.waiting || this.useServer() || this.nativeTimer || window.speechSynthesis?.paused) return;
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
    if (this.nativeQueue()) return;                  // the app's voice is native; this would hold the media volume
    try {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (!AudioCtx) return;
      if (!this.audioCtx) this.audioCtx = new AudioCtx();
      if (this.audioCtx.state === "suspended") {
        this.audioCtx.resume().catch(() => {});
      }
      if (this.audioCtx.state !== "running") return;
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
    // the phone's own voice, only when it is in use (each call starts the app's playback service)
    let phoneBusy = !!this.nativeTimer;
    try { phoneBusy = phoneBusy || (this.native() && typeof window.RayAndroid.isSpeaking === "function" && window.RayAndroid.isSpeaking()); } catch (e) {}
    if (phoneBusy && typeof window.RayAndroid.stopSpeaking === "function") window.RayAndroid.stopSpeaking();
    clearInterval(this.nativeTimer);
    this.nativeTimer = null;
    this.holdHeadset(false);
    if (typeof RayFace !== "undefined") RayFace.end(this.speaking && this.currentIndex >= this.queue.length);
    this.stopWatchdog();
    this.releaseWakeLock();
    this.stopAudioKeepAlive();
    this.clearMediaSession();
    if (window.speechSynthesis) { try { window.speechSynthesis.cancel(); } catch (e) {} }
    const src = this.currentSource;
    this.currentSource = null;
    if (src) { try { src.stop(); } catch (e) {} }
    this.prefetch = [];
    if (this.paused && this.audioCtx) { try { this.audioCtx.resume(); } catch (e) {} }
    this.updateButtonState(false);
    this.speaking = false;
    this.paused = false;
    this.streamOpen = false;
    this.waiting = false;
    clearTimeout(this.waitTimer);
    this.queue = [];
    this.currentIndex = 0;
    this.currentUtterance = null;
    this.activeBtn = null;
    this.activeMsg = null;
  },

  pause() {
    if (!this.speaking) return;
    if (window.speechSynthesis) { try { window.speechSynthesis.pause(); } catch (e) {} }
    if (this.currentSource && this.audioCtx) { try { this.audioCtx.suspend(); } catch (e) {} }
    this.paused = true;
    if (typeof RayFace !== "undefined") RayFace.pause(true);
    if ("mediaSession" in navigator) navigator.mediaSession.playbackState = "paused";
  },

  resume() {
    if (!this.speaking) return;
    if (window.speechSynthesis) { try { window.speechSynthesis.resume(); } catch (e) {} }
    if (this.currentSource && this.audioCtx) { try { this.audioCtx.resume(); } catch (e) {} }
    this.paused = false;
    if (typeof RayFace !== "undefined") RayFace.pause(false);
    if ("mediaSession" in navigator) navigator.mediaSession.playbackState = "playing";
  },

  speakText(rawText, btn = null, msgObj = null) {
    if (!window.speechSynthesis && !this.useServer() && !this.native()) {
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

  // --- a reply read while it is written: streamStart, then streamSay per piece, streamDrop to cut a note, streamEnd ---
  streamStart(btn = null) {
    if (this.speaking) this.stop();
    this.queue = [];
    this.prefetch = [];
    this.currentIndex = 0;
    this.speaking = true;
    this.paused = false;
    this.streamOpen = true;
    this.waiting = true;                            // nothing to say yet
    this.activeBtn = btn;
    this.activeMsg = null;
    this.updateButtonState(true);
    this.acquireWakeLock();
    this.startAudioKeepAlive();
    this.updateMediaSession("Reading response...");
    this.startWatchdog();
    return this.queue;
  },

  streamSay(rawText) {
    if (!this.speaking || !this.streamOpen) return false;           // stopped meanwhile
    const clean = this.clean(rawText);
    if (!clean) return false;
    this.queue.push(...this.chunk(clean));
    if (this.useServer() && this.queue.length - 1 <= this.currentIndex + 1) this.fetchChunk(this.queue.length - 1);
    if (this.waiting) {
      this.waiting = false;
      clearTimeout(this.waitTimer);
      this.speakNext();
    }
    return true;
  },

  // keep the first `keep` pieces of the queue (never the one playing)
  streamDrop(keep) {
    const n = Math.max(keep, this.currentIndex + 1, this.nativeQueue() ? this.nativeSent : 0);
    if (this.queue.length > n) { this.queue.length = n; this.prefetch.length = Math.min(this.prefetch.length, n); }
  },

  streamEnd() {
    if (!this.streamOpen) return;
    this.streamOpen = false;
    if (this.waiting) this.stop();
  },

  speakNext() {
    if (this.speaking && this.streamOpen && this.currentIndex >= this.queue.length) {
      // the reply is still being written: wait for its next sentence, and think meanwhile if that takes a while
      this.waiting = true;
      clearTimeout(this.waitTimer);
      this.waitTimer = setTimeout(() => {
        if (this.waiting && this.orb()) RayFace.thinking(true);
      }, 700);
      return;
    }
    if (!this.speaking || this.currentIndex >= this.queue.length) {
      this.stop();
      return;
    }

    const chunk = this.queue[this.currentIndex];
    this.holdHeadset(true);
    if (this.useServer()) { this.playServerChunk(this.currentIndex); return; }
    if (typeof SpeechSynthesisUtterance === "undefined") {
      if (this.native()) { this.speakNative(chunk); return; }
      this.stop();
      toast("error", "TTS not supported", "Your browser does not support the Web Speech API.");
      return;
    }
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

  // the Android companion app's own voice (RayAndroid.speak), when the server voice is off or failed: one chunk at a
  // time, the next once the phone reports it has stopped speaking (or never started within 4 s)
  native() { return !!(window.RayAndroid && typeof window.RayAndroid.speak === "function"); },
  // Android app: after you spoke through a headset (helmet intercom), hold its call link while Ray reads aloud, so
  // the answer comes back through the headset (RayAndroid.holdHeadsetForSpeech decides whether a headset is in use)
  headsetHeld: false,
  holdHeadset(on) {
    if (this.headsetHeld === on) return;
    this.headsetHeld = on;
    try { if (window.RayAndroid && typeof window.RayAndroid.holdHeadsetForSpeech === "function") window.RayAndroid.holdHeadsetForSpeech(on); } catch (e) {}
  },
  nativeTimer: null,
  nativeSent: 0,                                    // chunks of this queue handed to the app's voice
  nativeSend() {
    while (this.nativeSent < this.queue.length) {
      window.RayAndroid.speakQueued(this.queue[this.nativeSent++], this.getRate(), this.getPitch());
    }
  },
  // the app's voice: a piece really sounding for `seconds`, or null when the sound stops (RayNativeBridge)
  voicePiece(text, seconds) {
    if (!this.speaking || !this.orb() || typeof RayFace === "undefined") return;
    if (text === null) RayFace.chunkEnd();
    else RayFace.speakTimed(text, seconds);
  },
  speakNative(chunk) {
    const queue = this.queue, orb = this.orb(), t0 = Date.now();
    let started = false;
    const queued = this.nativeQueue();
    if (queued) {
      this.nativeSent = this.currentIndex;
      this.nativeSend();
      if (orb) RayFace.thinking(true);               // until his voice arrives (voicePiece)
    } else {
      window.RayAndroid.speak(chunk);
      if (orb) RayFace.speakText(chunk, this.getRate());
    }
    clearInterval(this.nativeTimer);
    this.nativeTimer = setInterval(() => {
      if (!this.speaking || this.queue !== queue) { clearInterval(this.nativeTimer); this.nativeTimer = null; return; }
      if (queued) this.nativeSend();                 // chunks of a reply still being written
      let busy = false;
      try { busy = typeof window.RayAndroid.isSpeaking === "function" ? window.RayAndroid.isSpeaking() : false; } catch (e) {}
      if (busy) { started = true; return; }
      if (!started && Date.now() - t0 < 4000) return;
      clearInterval(this.nativeTimer);
      this.nativeTimer = null;
      if (orb) RayFace.chunkEnd();
      this.currentIndex = queued ? this.nativeSent : this.currentIndex + 1;
      this.speakNext();
    }, 250);
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

  // chunk i as decoded audio; the next chunk is fetched while this one plays.  Piper has no pitch: the audio is played
  // `pitch` times faster (higher) and asked from the server that much slower, so the pace stays the Speed setting.  A
  // chunk fetched before a slider moved is fetched again with the new values.
  fetchChunk(i) {
    const rate = this.getRate(), pitch = this.getPitch();
    const have = this.prefetch[i];
    if (!have || have.rate !== rate || have.pitch !== pitch) {
      const ctx = this.audio();
      const p = fetch("v1/audio/speech", {
        method: "POST", headers: headers(true),
        body: JSON.stringify({input: this.queue[i], speed: rate / pitch}),
      }).then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.arrayBuffer();
      }).then((ab) => ctx.decodeAudioData(ab));
      p.catch(() => {});
      this.prefetch[i] = Object.assign(p, {rate, pitch});
    }
    return this.prefetch[i];
  },

  async playServerChunk(i) {
    const queue = this.queue;
    let buf, pitch;
    try {
      const p = this.fetchChunk(i);
      pitch = p.pitch;
      buf = await p;
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
    if (ctx && ctx.state === "suspended" && !this.paused) {
      try {
        await ctx.resume();
      } catch (e) {
        console.warn("AudioContext resume blocked by browser autoplay policy:", e);
        return;
      }
    }
    const src = ctx.createBufferSource();
    src.buffer = buf;
    src.playbackRate.value = pitch;
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
    if (orb) RayFace.speakAudio(this.analyser, this.queue[i], ctx, ctx.currentTime, buf.duration / pitch);
    if (i + 1 < this.queue.length) this.fetchChunk(i + 1);
  },

  init() {
    if (window.speechSynthesis) {
      const updateVoices = () => this.populateVoiceSelector();
      window.speechSynthesis.onvoiceschanged = updateVoices;
      updateVoices();
    } else {
      // Android WebView: no browser voice, but Ray's server voice and the phone's own voice still read aloud
      const card = $("tts-settings-card");
      const note = card && card.querySelector(".muted.small");
      if (note) note.textContent = "No browser voice here: Ray's server voice reads aloud" + (this.native() ? ", or the phone's voice." : ".");
    }

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
    if (typeof RayFace !== "undefined") {
      RayFace.onStop = () => { this.stop(); RayFace.end(false); };   // a click stops it
      RayFace.onWake = () => wakeModelFromSleep();
    }
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
    const thinkToggle = $("tts-think-toggle");
    if (thinkToggle) {
      thinkToggle.setAttribute("aria-checked", String(this.isThinkAllOn()));
      thinkToggle.onclick = () => {
        const next = thinkToggle.getAttribute("aria-checked") !== "true";
        thinkToggle.setAttribute("aria-checked", String(next));
        store.set("tts_think_all", next);
        if (!next && typeof RayFace !== "undefined" && RayFace.state.mode === "think") RayFace.end(false);
      };
    }
    const streamToggle = $("tts-stream-toggle");
    if (streamToggle) {
      streamToggle.setAttribute("aria-checked", String(this.isStreamOn()));
      streamToggle.onclick = () => {
        const next = streamToggle.getAttribute("aria-checked") !== "true";
        streamToggle.setAttribute("aria-checked", String(next));
        store.set("tts_stream", next);
      };
    }
    const orbToggle = $("tts-orb-toggle");
    if (orbToggle) {
      orbToggle.setAttribute("aria-checked", String(this.isOrbOn()));
      orbToggle.onclick = () => {
        const next = orbToggle.getAttribute("aria-checked") !== "true";
        orbToggle.setAttribute("aria-checked", String(next));
        store.set("tts_orb", next);
        if (typeof RayFace !== "undefined") {
          if (!next) RayFace.leave(true);
          else if (modelUnloaded) RayFace.sleep(true);
        }
      };
    }
    const testBtn = $("tts-test-btn");
    if (testBtn) {
      testBtn.onclick = () => {
        const vSel = $("tts-voice-select");
        if (vSel && vSel.value) store.set("tts_voice", vSel.value);
        this.speakText("Hi, I'm Ray, the household's red panda, on the home server.", testBtn);
      };
    }
    this.updateSpeakToggleBtn();
  },

  populateVoiceSelector() {
    const sel = $("tts-voice-select");
    if (!sel || !window.speechSynthesis) return;
    const voices = window.speechSynthesis.getVoices();
    const countEl = $("tts-voice-count");
    if (countEl) countEl.textContent = `${voices.length} available`;
    const saved = store.get("tts_voice", "");

    sel.innerHTML = '<option value="">Auto (Ray: Piper HFC male)</option>';

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

