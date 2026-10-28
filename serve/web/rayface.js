// serve/web/rayface.js - Ray's face while she reads a reply aloud, and a small thinking face while she works on a
// spoken prompt.  The face is the first blue-white dot-matrix style (eyes and brows that show the mood of each
// sentence); the mouth is a dot-matrix waveform of her voice instead of lips, so it never pretends to form words.
//   - Server voice (Web Audio): the waveform's bars come from the voice's spectrum and loudness, read from an analyser
//     that sees the sound about 50 ms before it is heard (TTSController delays the output), so it leads the voice.
//   - Browser voice (no audio to read): the bars follow a loudness estimated from the text.
//   - The end: a warm look and a small nod, then a slow fade.  Clicking the face stops the speech (onStop).
// The motion is kept calm: slow easing, rare small glances, bars that rise quickly and fall slowly.
"use strict";

const RayFace = (() => {
  const COLS = 44, ROWS = 26;                 // the face's own grid; a wider panel shows more dark dots around it
  const BARS = 9;                             // waveform columns each side of the centre
  const FADE_OUT = 700, WARM_MS = 1800;
  const ON = "#e6f8ff", BLUE = (a) => `rgba(56,189,248,${a})`, OFF = "rgba(56,189,248,0.07)";

  // expressions: eye openness, happy eye arcs, brow height/tilt/asymmetry, waveform smile, gaze
  const EXPR = {
    neutral:   {eyeOpen: 1,    arc: 0,   browY: 0,    browTilt: 0,    browAsym: 0,   smile: 0.15, lookX: 0,    lookY: 0},
    happy:     {eyeOpen: 0.9,  arc: 0.7, browY: -0.4, browTilt: 0,    browAsym: 0,   smile: 0.6,  lookX: 0,    lookY: 0},
    excited:   {eyeOpen: 1.1,  arc: 0.2, browY: -1,   browTilt: 0,    browAsym: 0,   smile: 0.65, lookX: 0,    lookY: -0.2},
    surprised: {eyeOpen: 1.25, arc: 0,   browY: -1.4, browTilt: 0,    browAsym: 0,   smile: 0,    lookX: 0,    lookY: -0.2},
    curious:   {eyeOpen: 1.05, arc: 0,   browY: -0.4, browTilt: 0,    browAsym: 1,   smile: 0.2,  lookX: 0.4,  lookY: -0.1},
    thinking:  {eyeOpen: 0.85, arc: 0,   browY: -0.2, browTilt: -0.3, browAsym: 0.7, smile: 0,    lookX: -0.7, lookY: -0.6},
    concerned: {eyeOpen: 0.85, arc: 0,   browY: 0.2,  browTilt: 1,    browAsym: 0,   smile: -0.4, lookX: 0,    lookY: 0.3},
    warm:      {eyeOpen: 0.8,  arc: 1,   browY: -0.3, browTilt: 0.2,  browAsym: 0,   smile: 0.8,  lookX: 0,    lookY: 0.2},
  };
  const RULES = [
    ["concerned", /\b(error|errors|fail|fails|failed|failing|sorry|unfortunately|can't|cannot|couldn't|won't|warning|problem|broken|crash(ed)?|denied|refused|missing|lost|wrong|issue)\b/i],
    ["surprised", /\b(wow|whoa|huh)\b|\boh\b.*!/i],
    ["excited",   /!\s*$/],
    ["curious",   /\?\s*$/],
    ["happy",     /\b(done|great|success(ful(ly)?)?|works|worked|fixed|passed|ready|nice|glad|perfect|thanks|thank you|hello|hi|hey|awesome|welcome)\b|[😊🎉✅🙂]/iu],
    ["thinking",  /\b(maybe|perhaps|let me|hmm|probably|might|not sure|i think|wonder)\b/i],
  ];
  const moodOf = (sentence) => (RULES.find(([, re]) => re.test(sentence)) || ["neutral"])[0];

  let el = null, canvas = null, g = null, raf = 0, visible = false, hideTimer = 0, warmTimer = 0, onStop = null;
  const geo = {pitch: 6, cols: COLS, rows: ROWS, offX: 0, offY: 0, laidW: 0, laidH: 0};
  const cur = {...EXPR.neutral, blink: 0, nod: 0};
  let target = {...EXPR.neutral};
  const bars = new Float32Array(BARS + 1);    // waveform half-heights in cells, centre first
  let level = 0, paused = false, mode = "idle";   // "audio" | "text" | "warm" | "idle"
  let analyser = null, tbuf = null, fbuf = null;
  let line = null;                            // the chunk being spoken: {text, times[], amp[], sentences[], total, …}
  let audioText = null, audioStart = 0, audioDur = 0, audioCtx = null;
  let speed = 1;
  let nextBlink = 0, blinkUntil = 0, nodStart = 0, nextGlance = 0, glance = {x: 0, y: 0};

  function mount() {
    if (el) return true;
    el = document.getElementById("ray-face");
    if (!el) return false;
    canvas = el.querySelector("canvas");
    g = canvas.getContext("2d");
    el.addEventListener("click", () => onStop && onStop());
    el.addEventListener("keydown", (e) => {
      if ((e.key === "Enter" || e.key === " ") && onStop) { e.preventDefault(); onStop(); }
    });
    return true;
  }

  // fit the dot grid to a canvas's size (once per size change)
  function fit(cv, q) {
    const r = cv.getBoundingClientRect();
    if (!r.width || !r.height || (r.width === q.laidW && r.height === q.laidH)) return;
    q.laidW = r.width; q.laidH = r.height;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    cv.width = Math.round(r.width * dpr);
    cv.height = Math.round(r.height * dpr);
    q.pitch = Math.min(r.width / (COLS + 2), r.height / (ROWS + 2)) * dpr;
    q.cols = Math.floor(cv.width / q.pitch);
    q.rows = Math.floor(cv.height / q.pitch);
    q.offX = (cv.width - q.cols * q.pitch) / 2;
    q.offY = (cv.height - q.rows * q.pitch) / 2;
  }
  const layout = () => fit(canvas, geo);

  // a chunk's text: when each character is reached (seconds at rate 1), how loud it is likely to be, sentence moods
  function plan(text) {
    const times = [], amp = [], sentences = [];
    let t = 0, s0 = 0;
    for (let i = 0; i < text.length; i++) {
      times.push(t);
      const ch = text[i];
      if (/[aeiouy]/i.test(ch)) { amp.push(0.9); t += 0.085; }
      else if (/[a-z0-9]/i.test(ch)) { amp.push(0.4); t += 0.06; }
      else if (/[.!?]/.test(ch)) { amp.push(0); t += 0.42; }
      else if (/[,;:]/.test(ch)) { amp.push(0); t += 0.22; }
      else { amp.push(0.1); t += 0.04; }
      if (/[.!?\n]/.test(ch) || i === text.length - 1) {
        sentences.push({from: s0, to: i, mood: moodOf(text.slice(s0, i + 1).trim())});
        s0 = i + 1;
      }
    }
    times.push(t);
    return {text, times, amp, sentences, total: t};
  }
  const charAt = (p, sec) => {
    let i = 0;
    while (i < p.text.length && p.times[i + 1] <= sec) i++;
    return i;
  };

  // the voice's spectrum as BARS+1 band levels (low bands in the middle of the mouth), and its loudness
  function readAudio(out) {
    const n = analyser.fftSize;
    if (!tbuf || tbuf.length !== n) { tbuf = new Float32Array(n); fbuf = new Uint8Array(analyser.frequencyBinCount); }
    analyser.getFloatTimeDomainData(tbuf);
    let sum = 0;
    for (let i = 0; i < n; i++) sum += tbuf[i] * tbuf[i];
    const loud = Math.max(0, Math.min(1, (Math.sqrt(sum / n) - 0.012) / 0.14));   // a noise gate, speech ~0.02-0.2
    analyser.getByteFrequencyData(fbuf);
    const hz = analyser.context.sampleRate / n;
    for (let b = 0; b <= BARS; b++) {
      const lo = 120 * Math.pow(4000 / 120, b / (BARS + 1)), hi = 120 * Math.pow(4000 / 120, (b + 1) / (BARS + 1));
      let m = 0, k = 0;
      for (let i = Math.floor(lo / hz); i <= Math.ceil(hi / hz) && i < fbuf.length; i++) { m += fbuf[i]; k++; }
      out[b] = k ? Math.max(0, (m / k - 70) / 150) : 0;
    }
    return loud;
  }

  const want = new Float32Array(BARS + 1);
  function step(now) {
    // the sentence being spoken sets the mood; the voice sets the waveform
    let loud = 0;
    want.fill(0);
    if (!paused && mode === "audio" && analyser) {
      loud = readAudio(want);
      if (audioText && audioDur > 0) {
        const sec = (audioCtx.currentTime - audioStart) / audioDur * audioText.total;
        const i = charAt(audioText, sec);
        const sen = audioText.sentences.find((s) => i >= s.from && i <= s.to);
        if (sen) target = {...EXPR[sen.mood]};
      }
    } else if (!paused && mode === "text" && line) {
      const base = line.times[line.anchorIdx] + (now - line.start) / 1000 * line.rate / speed - line.anchorT;
      const i = charAt(line, base);
      if (i < line.text.length) {
        loud = line.amp[i];
        const sen = line.sentences.find((s) => i >= s.from && i <= s.to);
        if (sen) target = {...EXPR[sen.mood]};
      }
      for (let b = 0; b <= BARS; b++) want[b] = (1 - b / (BARS + 2)) * (0.75 + 0.25 * Math.sin(now / 260 + b * 1.7));
    }
    level += (loud - level) * (loud > level ? 0.3 : 0.08);
    for (let b = 0; b <= BARS; b++) {
      const h = Math.min(3.4, level * (0.6 + 2.6 * want[b]));
      bars[b] += (h - bars[b]) * (h > bars[b] ? 0.32 : 0.09);    // up quickly, down slowly
    }

    // blinks, rare small glances and the closing nod
    if (now > nextBlink) { blinkUntil = now + 150; nextBlink = now + 3000 + Math.random() * 3000; }
    cur.blink = now < blinkUntil ? 1 : 0;
    if (now > nextGlance) {
      glance = Math.random() < 0.6 ? {x: 0, y: 0} : {x: (Math.random() - 0.5) * 0.8, y: (Math.random() - 0.5) * 0.4};
      nextGlance = now + 3500 + Math.random() * 3500;
    }
    cur.nod = nodStart ? Math.sin(Math.min(1, (now - nodStart) / 900) * Math.PI) * 0.7 : 0;
    for (const k of Object.keys(EXPR.neutral)) {
      const v = target[k] + (k === "lookX" ? glance.x : k === "lookY" ? glance.y : 0);
      cur[k] += (v - cur[k]) * 0.06;
    }
  }

  // brightness 0-1 at grid cell (x, y), in face coordinates (0..COLS, 0..ROWS), for face state c with waveform bars
  // (bb); shimmer (0-1, or -1 for none) is a soft bright spot moving along a silent mouth line
  function shade(x, y, c, bb, shimmer) {
    const gx = c.lookX * 1.2, gy = c.lookY * 0.8 + c.nod * 1.5;
    let v = 0;
    const soft = (d) => Math.max(0, Math.min(1, 0.6 - d));
    for (const side of [-1, 1]) {
      // eye: a filled oval, blended into an upward arc when happy
      const ex = COLS / 2 + side * 9 + gx, ey = 10 + gy;
      const rx = 4.6, ry = Math.max(0.35, 3.3 * c.eyeOpen * (1 - c.blink * 0.9));
      const dx = (x - ex) / rx, dy = (y - ey) / ry;
      const r = Math.hypot(dx, dy);
      const filled = soft((r - 1) * Math.min(rx, ry));
      const ay = (y - (ey + 1.4)) / 3.4, ar = Math.hypot(dx, ay);
      const arc = y <= ey + 1.4 ? soft(Math.abs(ar - 1) * 3.2 - 0.4) : 0;
      v = Math.max(v, filled * (1 - c.arc) + arc * c.arc);
      // brow: a short bar above the eye; tilt raises the inner end, asymmetry raises the right brow
      const bx = (x - ex) / 4.2;
      if (Math.abs(bx) <= 1) {
        const inner = side < 0 ? bx : -bx;            // +1 at the end nearest the nose
        const by = ey - 5.4 + c.browY - c.browTilt * inner * 1.1 - (side > 0 ? c.browAsym : 0) - (c.eyeOpen - 1) * 2;
        v = Math.max(v, soft(Math.abs(y - by) - 0.15) * 0.75);
      }
    }
    // mouth: a waveform of the voice on a line that curves up when smiling; silent, it is just the line
    const mx = COLS / 2 + gx * 0.5, my = 19.5 + gy * 0.6;
    const col = Math.round(x - 0.5 - mx);
    if (Math.abs(col) <= BARS) {
      const u = col / (BARS + 0.5);
      const base = my - c.smile * 0.9 + c.smile * 1.8 * (1 - u * u);
      const h = bb[Math.abs(col)] * (1 - 0.35 * u * u);
      const d = Math.abs(y - base);
      const line = shimmer < 0 ? 1 : 0.45 + 0.55 * Math.exp(-(((u + 1) / 2 - shimmer) ** 2) / 0.02);
      if (d <= h + 0.5) v = Math.max(v, d < 0.6 ? line : 0.95 - 0.35 * (d / (h + 0.5)));
    }
    return v;
  }

  function paint(gc, cv, q, c, bb, shimmer = -1) {
    gc.clearRect(0, 0, cv.width, cv.height);
    const fx = Math.floor((q.cols - COLS) / 2), fy = Math.floor((q.rows - ROWS) / 2);
    const rad = q.pitch * 0.36;
    for (let j = 0; j < q.rows; j++) {
      for (let i = 0; i < q.cols; i++) {
        const v = shade(i - fx + 0.5, j - fy + 0.5, c, bb, shimmer);
        gc.fillStyle = v < 0.04 ? OFF : v > 0.8 ? ON : BLUE(0.25 + v * 0.75);
        gc.beginPath();
        gc.arc(q.offX + (i + 0.5) * q.pitch, q.offY + (j + 0.5) * q.pitch, v < 0.04 ? rad * 0.8 : rad, 0, Math.PI * 2);
        gc.fill();
      }
    }
  }
  const draw = () => paint(g, canvas, geo, cur, bars);

  function frame(now) {
    raf = 0;
    if (!visible) return;
    layout();
    step(now);
    draw();
    raf = requestAnimationFrame(frame);
  }
  function kick() { if (!raf) raf = requestAnimationFrame(frame); }

  function show() {
    if (!mount()) return;
    Thinking.hide();
    clearTimeout(hideTimer); clearTimeout(warmTimer);
    nodStart = 0;
    if (visible && el.classList.contains("is-on")) return;
    const composer = el.parentElement && el.parentElement.querySelector(".code-mobile-composer");
    if (composer) el.style.setProperty("--ray-face-bottom", `${composer.offsetHeight + 10}px`);
    target = {...EXPR.neutral};
    el.hidden = false;
    visible = true;
    layout();
    nextBlink = performance.now() + 1800;
    nextGlance = performance.now() + 3000;
    requestAnimationFrame(() => el.classList.add("is-on"));
    kick();
  }

  // --- what the web app calls ---

  // a chunk of server audio starts playing through `an`; `text` and `duration` give the sentence moods their timing
  function speakAudio(an, text, ctx, startAt, duration) {
    show();
    analyser = an;
    audioText = plan(text || "");
    audioCtx = ctx; audioStart = startAt; audioDur = duration;
    mode = "audio";
    paused = false;
  }

  // a chunk starts with the browser's voice
  function speakText(text, rate = 1) {
    show();
    line = {...plan(text), start: performance.now(), rate: rate || 1, anchorIdx: 0, anchorT: 0};
    mode = "text";
    paused = false;
  }

  // the browser voice reports the word at charIndex starting now
  function boundary(charIndex) {
    if (!line || charIndex == null || charIndex >= line.text.length) return;
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

  // Ray stopped talking: a warm look and a small nod, then the panel fades out slowly
  function end(finished = true) {
    Thinking.hide();
    if (!visible || !el) return;
    line = null; analyser = null; audioText = null;
    mode = "warm";
    target = {...EXPR.warm};
    nodStart = performance.now();
    clearTimeout(warmTimer); clearTimeout(hideTimer);
    warmTimer = setTimeout(() => {
      el.classList.remove("is-on");
      hideTimer = setTimeout(() => {
        el.hidden = true;
        visible = false;
        nodStart = 0;
        mode = "idle";
      }, FADE_OUT);
    }, finished ? WARM_MS : WARM_MS / 2);
  }

  // the thinking face: the same face, small, at the other side; eyes up and to the side, drifting slowly from one side
  // to the other, one brow raised in turn, an occasional blink, and a soft light moving along the closed mouth
  const Thinking = (() => {
    let tel = null, tc = null, tg = null, traf = 0, on = false, thide = 0, tBlink = 0, tBlinkUntil = 0;
    const q = {pitch: 6, cols: COLS, rows: ROWS, offX: 0, offY: 0, laidW: 0, laidH: 0};
    const tc0 = {...EXPR.thinking, blink: 0, nod: 0};
    const still = new Float32Array(BARS + 1);
    function frame(now) {
      traf = 0;
      if (!on) return;
      fit(tc, q);
      const side = Math.sin(now / 2600);                 // about 16 s for a full look left, right and back
      const t = {...EXPR.thinking, lookX: 0.8 * side, lookY: -0.65 + 0.1 * Math.sin(now / 1700),
                 browAsym: 0.7 * (side > 0 ? 1 : -0.4), smile: 0.02};
      for (const k of Object.keys(EXPR.neutral)) tc0[k] += (t[k] - tc0[k]) * 0.05;
      if (now > tBlink) { tBlinkUntil = now + 150; tBlink = now + 3500 + Math.random() * 3000; }
      tc0.blink = now < tBlinkUntil ? 1 : 0;
      if (q.laidW) paint(tg, tc, q, tc0, still, (now / 1800) % 1.4 - 0.2);
      traf = requestAnimationFrame(frame);
    }
    return {
      show() {
        tel = tel || document.getElementById("ray-think");
        if (!tel) return;
        tc = tc || tel.querySelector("canvas");
        tg = tg || tc.getContext("2d");
        clearTimeout(thide);
        const composer = tel.parentElement && tel.parentElement.querySelector(".code-mobile-composer");
        if (composer) tel.style.setProperty("--ray-face-bottom", `${composer.offsetHeight + 10}px`);
        tel.hidden = false;
        on = true;
        tBlink = performance.now() + 2000;
        requestAnimationFrame(() => tel.classList.add("is-on"));
        if (!traf) traf = requestAnimationFrame(frame);
      },
      hide() {
        if (!tel || !on) return;
        tel.classList.remove("is-on");
        thide = setTimeout(() => { tel.hidden = true; on = false; }, FADE_OUT);
      },
    };
  })();

  // a spoken prompt is being answered: the thinking face shows until Ray speaks (or the turn ends)
  function thinking() {
    if (mode === "audio" || mode === "text") return;   // already speaking
    if (visible) {                                      // still saying goodbye to the last reply: let it go now
      clearTimeout(warmTimer); clearTimeout(hideTimer);
      el.classList.remove("is-on");
      hideTimer = setTimeout(() => { el.hidden = true; visible = false; nodStart = 0; mode = "idle"; }, FADE_OUT);
    }
    Thinking.show();
  }

  window.addEventListener("resize", () => { if (visible) layout(); });
  return {thinking, speakAudio, speakText, boundary, chunkEnd, pause, end, moodOf,
          get visible() { return visible; }, get state() { return {...cur, mode, level, bars: [...bars]}; },
          set onStop(fn) { onStop = fn; }};
})();
