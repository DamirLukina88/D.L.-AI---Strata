// serve/web/app-03-stt.js - part of the web app (see app-01-util.js): Speech-to-Text (STT) native engine.
// A classic script, loaded in order by index.html; it shares its globals with the others.
"use strict";

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
    if (typeof window !== "undefined" && window.RayAndroid && typeof window.RayAndroid.startListening === "function") {
      if (typeof TTSController !== "undefined" && TTSController.speaking) {
        TTSController.stop();
      }
      this.currentTarget = target;
      this.isRecording = true;
      this.updateMicUI(true);
      window.RayAndroid.startListening();
      return;
    }
    const engine = this.getEngine();
    if (engine === "whisper") {
      return this.startMediaRecorder(target);
    }
    return this.startBrowserSpeech(target);
  },

  stop() {
    this.clearSilenceTimer();
    if (typeof window !== "undefined" && window.RayAndroid && typeof window.RayAndroid.stopListening === "function") {
      try { window.RayAndroid.stopListening(); } catch (_) {}
      this.isRecording = false;
      this.updateMicUI(false);
      this.restoreKeyboard(this.currentTarget);
    }
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

  handleNativeSpeechResult(text, isFinal) {
    if (!text) return;
    const target = this.currentTarget || "code";
    const ta = this.getTargetInput(target);
    if (ta) {
      ta.value = text;
      try { ta.selectionStart = ta.selectionEnd = ta.value.length; } catch (_) {}
      ta.dispatchEvent(new Event("input", { bubbles: true }));
    }
    this.lastInputWasVoice = true;
    this.lastTranscribedText = text;
    if (isFinal) {
      this.isRecording = false;
      this.updateMicUI(false);
      // the phone's recognizer has no cleanup() of its own: give the keyboard back (dismissKeyboard took it away)
      this.restoreKeyboard(target);
      if (this.autoSend) {
        this.scheduleAutoSend(target);
      }
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

  // D.L. AI: the mic button's tap / hold on a key, for the Xiaomi remote's Assistant button (remapped to Pause by
  // /etc/udev/hwdb.d/70-xiaomi-rc.hwdb). Hold 400 ms or more to talk while held; a shorter tap toggles listening.
  bindKeyboardPTT(code, target) {
    let pressTimer = null;
    let isHold = false;
    document.addEventListener("keydown", (e) => {
      if (e.code !== code || e.repeat) return;
      e.preventDefault();
      isHold = false;
      pressTimer = setTimeout(() => {
        pressTimer = null;
        isHold = true;
        this.isPushToTalk = true;
        this.cancelAutoSendTimer();
        if (!this.isRecording && !this.isTranscribing) this.start(target);
      }, 400);
    });
    document.addEventListener("keyup", (e) => {
      if (e.code !== code) return;
      e.preventDefault();
      if (pressTimer) {
        clearTimeout(pressTimer);
        pressTimer = null;
        this.isPushToTalk = false;
        this.toggle(target);
      } else if (isHold) {
        isHold = false;
        this.isPushToTalk = false;
        if (this.isRecording && this.currentTarget === target) this.stop();
      }
    });
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
    this.bindKeyboardPTT("Pause", "code");

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

