// serve/web/rayorb.js - Ray's voice orb: a small blue blob that reacts to Ray's voice, at the side of the Code feed.
// It is not a face on purpose: a synthetic voice with a human face falls into the uncanny valley, a shape that moves
// with the sound reads as "Ray is speaking" without pretending to be a person.
//   - Server voice (web Audio): the blob follows the audio's loudness and pitch, read from an analyser that sees the
//     sound about 50 ms before it is heard (TTSController delays the output), so the motion leads the voice slightly.
//   - Browser voice (no audio to read): a pulse estimated from the text, vowels loud, pauses quiet.
//   - Thinking (a spoken prompt is being answered): the colour shifts to indigo and a highlight circles slowly.
//   - The end: the motion settles, one soft breath out, then a slow fade.  Clicking it stops the speech (onStop).
"use strict";

const RayOrb = (() => {
  const FADE_OUT = 700, SETTLE_MS = 1100;
  const BLUE = [56, 189, 248], CYAN = [103, 232, 249], WHITE = [230, 248, 255], INDIGO = [129, 140, 248];

  let el = null, canvas = null, g = null, raf = 0, visible = false, hideTimer = 0, settleTimer = 0;
  let size = 72, dpr = 1, onStop = null;
  let mode = "idle";                          // "think" | "audio" | "text" | "settle" | "idle"
  let analyser = null, buf = null, freq = null;
  let level = 0, pitch = 0.4, think = 0, settleAt = 0, onsetAt = -1e9, lastLevel = 0, paused = false;
  let line = null;                            // browser voice: {amp[], times[], total, start, rate, anchorIdx, anchorT}
  let speed = 1;
  const rings = [];                           // expanding rings on strong onsets

  function mount() {
    if (el) return true;
    el = document.getElementById("ray-orb");
    if (!el) return false;
    canvas = el.querySelector("canvas");
    g = canvas.getContext("2d");
    el.addEventListener("click", () => onStop && onStop());
    el.addEventListener("keydown", (e) => {
      if ((e.key === "Enter" || e.key === " ") && onStop) { e.preventDefault(); onStop(); }
    });
    return true;
  }

  function layout() {
    const r = canvas.getBoundingClientRect();
    const s = Math.round(Math.min(r.width, r.height));
    if (!s) return;
    const d = Math.min(window.devicePixelRatio || 1, 2);
    if (s === size && d === dpr && canvas.width) return;
    size = s; dpr = d;
    canvas.width = canvas.height = Math.round(s * d);
  }

  // browser voice: how loud each character is likely to be, on an estimated timeline (seconds at rate 1)
  function plan(text) {
    const amp = [], times = [];
    let t = 0;
    for (const ch of text) {
      times.push(t);
      if (/[aeiouy]/i.test(ch)) { amp.push(0.85); t += 0.085; }
      else if (/[a-z0-9]/i.test(ch)) { amp.push(0.35); t += 0.06; }
      else if (/[.!?]/.test(ch)) { amp.push(0); t += 0.42; }
      else if (/[,;:]/.test(ch)) { amp.push(0); t += 0.22; }
      else { amp.push(0.05); t += 0.04; }
    }
    times.push(t);
    return {amp, times, total: t};
  }

  function readAudio() {
    if (!buf || buf.length !== analyser.fftSize) {
      buf = new Float32Array(analyser.fftSize);
      freq = new Uint8Array(analyser.frequencyBinCount);
    }
    analyser.getFloatTimeDomainData(buf);
    let sum = 0;
    for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i];
    const rms = Math.sqrt(sum / buf.length);
    const loud = Math.max(0, Math.min(1, (rms - 0.012) / 0.14));   // a noise gate, then speech is about 0.02-0.2
    // brightness of the voice: the spectral centroid of the speech band, 0 low to 1 high
    analyser.getByteFrequencyData(freq);
    let num = 0, den = 0;
    const hz = analyser.context.sampleRate / analyser.fftSize;
    for (let i = Math.floor(80 / hz); i < Math.min(freq.length, 5000 / hz); i++) { num += i * hz * freq[i]; den += freq[i]; }
    const cen = den > 0 ? Math.max(0, Math.min(1, (num / den - 600) / 2200)) : pitch;
    return [loud, cen];
  }

  function step(now) {
    let target = 0, tPitch = pitch;
    if (paused) target = 0;
    else if (mode === "audio" && analyser) [target, tPitch] = readAudio();
    else if (mode === "text" && line) {
      const base = line.times[line.anchorIdx] + (now - line.start) / 1000 * line.rate / speed - line.anchorT;
      let i = line.anchorIdx;
      while (i < line.amp.length && line.times[i + 1] <= base) i++;
      target = i < line.amp.length ? line.amp[i] * (0.75 + 0.25 * Math.sin(now / 47)) : 0;
    }
    // fast attack, slower release, as real-time lip sync does
    level += (target - level) * (target > level ? 0.55 : 0.14);
    pitch += (tPitch - pitch) * 0.08;
    think += ((mode === "think" ? 1 : 0) - think) * 0.06;
    if (level - lastLevel > 0.22 && now - onsetAt > 260) { onsetAt = now; rings.push({at: now, from: level}); }
    lastLevel = level;
  }

  const mix = (a, b, t) => a.map((v, i) => Math.round(v + (b[i] - v) * t));
  const rgba = (c, a) => `rgba(${c[0]},${c[1]},${c[2]},${a})`;

  function draw(now) {
    const W = canvas.width, c = W / 2, t = now / 1000;
    g.clearRect(0, 0, W, W);
    // settle: one soft breath out after the voice ends
    const sp = mode === "settle" ? Math.min(1, (now - settleAt) / SETTLE_MS) : 0;
    const exhale = mode === "settle" ? Math.sin(sp * Math.PI) * 0.07 : 0;
    const breath = Math.sin(t * Math.PI * 2 / 4) * 0.025;
    const r0 = W * 0.27 * (1 + breath + 0.16 * level + exhale);
    // colour: blue at rest, towards cyan and white with a bright voice, indigo while thinking, softer when settling
    let col = mix(BLUE, CYAN, Math.min(1, pitch * 0.8 + level * 0.3));
    col = mix(col, INDIGO, think);
    const core = mix(WHITE, INDIGO, think * 0.5);

    // halo
    const halo = g.createRadialGradient(c, c, r0 * 0.6, c, c, W * 0.5);
    halo.addColorStop(0, rgba(col, 0.22 + 0.25 * level + 0.1 * think));
    halo.addColorStop(1, rgba(col, 0));
    g.fillStyle = halo;
    g.fillRect(0, 0, W, W);

    // rings on strong onsets
    for (let i = rings.length - 1; i >= 0; i--) {
      const k = (now - rings[i].at) / 700;
      if (k >= 1) { rings.splice(i, 1); continue; }
      g.strokeStyle = rgba(col, (1 - k) * 0.45 * rings[i].from);
      g.lineWidth = 1.5 * dpr;
      g.beginPath();
      g.arc(c, c, r0 * (1.05 + k * 0.7), 0, Math.PI * 2);
      g.stroke();
    }

    // the blob: a circle whose edge waves with the voice; louder voice, bigger waves; brighter voice, faster ripples
    const amp = 0.03 + 0.16 * level;
    const f2 = 1.6 + pitch * 2.2;
    g.beginPath();
    for (let k = 0; k <= 72; k++) {
      const a = k / 72 * Math.PI * 2;
      const wave = Math.sin(3 * a + t * f2) * 0.5 + Math.sin(5 * a - t * (f2 * 1.4) + pitch * 3) * 0.32
                 + Math.sin(2 * a + t * 0.9) * 0.4;
      const r = r0 * (1 + amp * wave * 0.6);
      const x = c + r * Math.cos(a), y = c + r * Math.sin(a);
      if (k) g.lineTo(x, y); else g.moveTo(x, y);
    }
    g.closePath();
    const body = g.createRadialGradient(c - r0 * 0.25, c - r0 * 0.3, r0 * 0.1, c, c, r0 * 1.1);
    body.addColorStop(0, rgba(core, 0.85 + 0.15 * level));
    body.addColorStop(0.45, rgba(col, 0.85));
    body.addColorStop(1, rgba(col, 0.25));
    g.fillStyle = body;
    g.fill();

    // thinking: a highlight arc circling slowly inside the edge
    if (think > 0.02) {
      const a0 = t * 1.6;
      g.strokeStyle = rgba(WHITE, 0.55 * think);
      g.lineWidth = 2 * dpr;
      g.lineCap = "round";
      g.beginPath();
      g.arc(c, c, r0 * 0.78, a0, a0 + 1.1);
      g.stroke();
    }
  }

  function frame(now) {
    raf = 0;
    if (!visible) return;
    layout();
    step(now);
    draw(now);
    raf = requestAnimationFrame(frame);
  }
  function kick() { if (!raf) raf = requestAnimationFrame(frame); }

  function show() {
    if (!mount()) return;
    clearTimeout(hideTimer); clearTimeout(settleTimer);
    if (visible && el.classList.contains("is-on")) return;
    const composer = el.parentElement && el.parentElement.querySelector(".code-mobile-composer");
    if (composer) el.style.setProperty("--ray-orb-bottom", `${composer.offsetHeight + 10}px`);
    el.hidden = false;
    visible = true;
    layout();
    requestAnimationFrame(() => el.classList.add("is-on"));
    kick();
  }

  // --- what the web app calls ---

  // a spoken prompt is being answered: show the orb thinking until the answer is read aloud
  function thinking() { show(); if (mode !== "audio" && mode !== "text") mode = "think"; }

  // a chunk of server audio starts playing through `an`
  function speakAudio(an) {
    show();
    analyser = an;
    mode = "audio";
    paused = false;
  }

  // a chunk starts with the browser's voice
  function speakText(text, rate = 1) {
    show();
    const p = plan(text);
    line = {...p, start: performance.now(), rate: rate || 1, anchorIdx: 0, anchorT: 0};
    mode = "text";
    paused = false;
  }

  // the browser voice reports the word at charIndex starting now
  function boundary(charIndex) {
    if (!line || charIndex == null || charIndex >= line.amp.length) return;
    line.anchorIdx = charIndex;
    line.anchorT = (performance.now() - line.start) / 1000 * line.rate / speed;
  }

  function chunkEnd() {
    if (mode === "text" && line) {
      const real = (performance.now() - line.start) / 1000 * line.rate;
      if (line.total > 0.6 && real > 0.3) speed = Math.max(0.6, Math.min(1.8, speed * 0.6 + (real / line.total) * 0.4));
      line = null;
    }
  }

  function pause(on) { paused = !!on; }

  // the voice ended (or the turn ended without speech): settle, then fade out slowly
  function end(finished = true) {
    if (!visible || !el) return;
    line = null;
    analyser = null;
    mode = "settle";
    settleAt = performance.now();
    clearTimeout(settleTimer); clearTimeout(hideTimer);
    settleTimer = setTimeout(() => {
      el.classList.remove("is-on");
      hideTimer = setTimeout(() => {
        el.hidden = true;
        visible = false;
        mode = "idle";
        level = 0; think = 0;
      }, FADE_OUT);
    }, finished ? SETTLE_MS : SETTLE_MS / 2);
  }

  window.addEventListener("resize", () => { if (visible) layout(); });
  return {thinking, speakAudio, speakText, boundary, chunkEnd, pause, end,
          get visible() { return visible; }, get state() { return {mode, level, pitch, think}; },
          set onStop(fn) { onStop = fn; }};
})();
