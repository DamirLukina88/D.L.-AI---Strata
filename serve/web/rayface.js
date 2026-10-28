// serve/web/rayface.js - Ray's talking face: a blue-white dot-matrix face shown only while Ray reads a reply aloud.
// The browser's speech engine gives no audio to analyse, so the mouth follows the text: each word becomes mouth shapes
// (web/lipsync-en.js, TalkingHead's English rules) on an estimated timeline with pauses at spaces and punctuation;
// word-boundary events resync it where the browser sends them, and the speed is corrected from each chunk's real
// length. Expressions come from simple rules on each sentence. Clicking the face stops the speech (onStop).
"use strict";

const RayFace = (() => {
  const COLS = 44, ROWS = 26;                 // the face's own grid; a wide panel shows more dark dots around it
  const UNIT = 0.088;                        // seconds per average mouth shape at rate 1 (corrected while speaking)
  const FADE_IN = 140, FADE_OUT = 240, WARM_MS = 1000;

  // Oculus visemes as mouth shapes: [width 0-1, opening 0-1]
  const VIS = {sil: [0.55, 0], aa: [0.75, 1], E: [0.85, 0.55], I: [0.9, 0.35], O: [0.45, 0.8], U: [0.32, 0.4],
               PP: [0.5, 0], FF: [0.62, 0.12], TH: [0.66, 0.22], DD: [0.66, 0.3], kk: [0.66, 0.35], CH: [0.5, 0.32],
               SS: [0.82, 0.15], nn: [0.66, 0.25], RR: [0.45, 0.3]};
  // pauses in mouth-shape units after a character that is not part of a word
  const PAUSE = {" ": 0.8, ",": 3.5, ";": 3.5, ":": 3.5, ".": 5.5, "!": 5.5, "?": 5.5, "\n": 4, "-": 0.5};
  const DIGIT = ["oh", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"];

  // expressions: eye openness, happy eye arcs, brow height/tilt/asymmetry, mouth smile, gaze
  const EXPR = {
    neutral:   {eyeOpen: 1,    arc: 0,   browY: 0,    browTilt: 0,    browAsym: 0,   smile: 0.15, lookX: 0,    lookY: 0},
    happy:     {eyeOpen: 0.9,  arc: 0.7, browY: -0.4, browTilt: 0,    browAsym: 0,   smile: 0.75, lookX: 0,    lookY: 0},
    excited:   {eyeOpen: 1.15, arc: 0.2, browY: -1.2, browTilt: 0,    browAsym: 0,   smile: 0.8,  lookX: 0,    lookY: -0.3},
    surprised: {eyeOpen: 1.3,  arc: 0,   browY: -1.6, browTilt: 0,    browAsym: 0,   smile: 0,    lookX: 0,    lookY: -0.2},
    curious:   {eyeOpen: 1.05, arc: 0,   browY: -0.4, browTilt: 0,    browAsym: 1.2, smile: 0.2,  lookX: 0.6,  lookY: -0.2},
    thinking:  {eyeOpen: 0.85, arc: 0,   browY: -0.2, browTilt: -0.3, browAsym: 0.8, smile: 0,    lookX: -1,   lookY: -0.8},
    concerned: {eyeOpen: 0.85, arc: 0,   browY: 0.2,  browTilt: 1,    browAsym: 0,   smile: -0.45,lookX: 0,    lookY: 0.4},
    warm:      {eyeOpen: 0.8,  arc: 1,   browY: -0.3, browTilt: 0.2,  browAsym: 0,   smile: 0.95, lookX: 0,    lookY: 0.2},
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

  let el = null, canvas = null, ctx = null, raf = 0, visible = false, hideTimer = 0, warmTimer = 0;
  let pitch = 6, cols = COLS, rows = ROWS, offX = 0, offY = 0, dpr = 1;
  const cur = {...EXPR.neutral, mouthW: VIS.sil[0], mouthOpen: 0, blink: 0, nod: 0};
  let target = {...EXPR.neutral};
  let mouthTarget = VIS.sil;
  let onStop = null;
  let speed = 1;                              // learned: real speech time / estimated time
  // the chunk being spoken
  let line = null;                            // {text, times[], track[], sentences[], total, start, rate, anchor…}
  let paused = 0, pauseAt = 0;
  let nextBlink = 0, blinkUntil = 0, nodStart = 0, nextGlance = 0, glance = {x: 0, y: 0};
  const reduced = () => window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;

  function mount() {
    if (el) return true;
    el = document.getElementById("ray-face");
    if (!el) return false;
    canvas = el.querySelector("canvas");
    ctx = canvas.getContext("2d");
    el.addEventListener("click", () => onStop && onStop());
    el.addEventListener("keydown", (e) => {
      if ((e.key === "Enter" || e.key === " ") && onStop) { e.preventDefault(); onStop(); }
    });
    return true;
  }

  let laidW = 0, laidH = 0;
  function layout() {
    const r = canvas.getBoundingClientRect();
    if (!r.width || !r.height || (r.width === laidW && r.height === laidH)) return;
    laidW = r.width; laidH = r.height;
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(r.width * dpr);
    canvas.height = Math.round(r.height * dpr);
    pitch = Math.min(r.width / (COLS + 2), r.height / (ROWS + 2)) * dpr;
    cols = Math.floor(canvas.width / pitch);
    rows = Math.floor(canvas.height / pitch);
    offX = (canvas.width - cols * pitch) / 2;
    offY = (canvas.height - rows * pitch) / 2;
  }

  // the timeline of one chunk at rate 1, in seconds: the mouth shapes (track), when each character is reached (times,
  // for word-boundary resync) and each sentence's mood
  function plan(text) {
    const times = new Array(text.length + 1).fill(0);
    const track = [];
    const sentences = [];
    let t = 0, i = 0;
    const word = (w, from, to) => {
      const o = LipsyncEn.wordsToVisemes(w);
      const dur = o.durations.reduce((a, d) => a + d, 0) || 1;
      o.visemes.forEach((v, k) => track.push({t: t + o.times[k] * UNIT, vis: VIS[v] || VIS.nn}));
      for (let c = from; c < to; c++) times[c] = t + (c - from) / (to - from) * dur * UNIT;
      t += dur * UNIT;
    };
    while (i < text.length) {
      const m = /^[A-Za-z\u00c0-\u024f']+|^\d+/.exec(text.slice(i, i + 40));
      if (m) {
        const w = /\d/.test(m[0]) ? [...m[0]].map((d) => DIGIT[d]).join(" ") : m[0];
        word(w, i, i + m[0].length);
        i += m[0].length;
        continue;
      }
      times[i] = t;
      track.push({t, vis: VIS.sil});
      t += (PAUSE[text[i]] ?? (/\s/.test(text[i]) ? 0.8 : 0)) * UNIT;
      i++;
    }
    times[text.length] = t;
    let s0 = 0;
    for (let c = 0; c < text.length; c++) {
      if (/[.!?\n]/.test(text[c]) || c === text.length - 1) {
        sentences.push({from: s0, to: c, mood: moodOf(text.slice(s0, c + 1).trim())});
        s0 = c + 1;
      }
    }
    return {times, track, sentences, total: t};
  }

  function frame(now) {
    raf = 0;
    if (!visible) return;
    layout();                                 // the phone strip grows from 0 px while it fades in
    step(now);
    draw();
    raf = requestAnimationFrame(frame);
  }
  function kick() { if (!raf) raf = requestAnimationFrame(frame); }

  function step(now) {
    // where the voice is in the current chunk
    if (line && !paused) {
      const elapsed = (now - line.start) / 1000 * line.rate / speed;
      const base = line.times[line.anchorIdx] + elapsed - line.anchorT;
      let i = line.anchorIdx;
      while (i < line.text.length && line.times[i + 1] <= base) i++;
      if (base >= line.total) mouthTarget = VIS.sil;
      else {
        let k = 0;
        while (k + 1 < line.track.length && line.track[k + 1].t <= base) k++;
        mouthTarget = line.track.length ? line.track[k].vis : VIS.sil;
      }
      const sen = line.sentences.find((x) => i >= x.from && i <= x.to);
      if (sen) target = {...EXPR[sen.mood]};
    } else {
      mouthTarget = VIS.sil;
    }

    // blinks, small glances and the closing nod
    if (now > nextBlink) { blinkUntil = now + 130; nextBlink = now + 2200 + Math.random() * 3200; }
    cur.blink = now < blinkUntil ? 1 : 0;
    if (now > nextGlance) {
      glance = Math.random() < 0.5 ? {x: 0, y: 0} : {x: (Math.random() - 0.5) * 1.2, y: (Math.random() - 0.5) * 0.6};
      nextGlance = now + 900 + Math.random() * 1800;
    }
    cur.nod = nodStart ? Math.sin(Math.min(1, (now - nodStart) / 700) * Math.PI) : 0;

    const ease = (k, v, f) => { cur[k] += (v - cur[k]) * f; };
    for (const k of Object.keys(EXPR.neutral)) ease(k, target[k] + (k === "lookX" ? glance.x : k === "lookY" ? glance.y : 0), 0.12);
    ease("mouthW", mouthTarget[0], 0.45);
    ease("mouthOpen", mouthTarget[1], 0.45);
  }

  // brightness 0-1 of the face at grid cell (x, y), in face coordinates (0..COLS, 0..ROWS)
  function shade(x, y) {
    const c = cur;
    const gx = c.lookX * 1.2, gy = c.lookY * 0.8 + c.nod * 1.5;
    let v = 0;
    const soft = (d) => Math.max(0, Math.min(1, 0.6 - d));
    for (const side of [-1, 1]) {
      // eye: a filled oval, blended into an upward arc when happy
      const ex = COLS / 2 + side * 9 + gx, ey = 10 + gy;
      const rx = 4.4, ry = Math.max(0.35, 3.5 * c.eyeOpen * (1 - c.blink * 0.9));
      const dx = (x - ex) / rx, dy = (y - ey) / ry;
      const r = Math.hypot(dx, dy);
      const filled = soft((r - 1) * Math.min(rx, ry));
      const ay = (y - (ey + 1.4)) / 3.4, ar = Math.hypot(dx, ay);
      const arc = y <= ey + 1.4 ? soft(Math.abs(ar - 1) * 3.2 - 0.4) : 0;
      v = Math.max(v, filled * (1 - c.arc) + arc * c.arc);
      // lashes: two dots flicking up and out from the outer corner
      const lt = ey - Math.max(ry * 0.5, 0.8);
      for (let k = 1; k <= 2; k++) v = Math.max(v, soft(Math.hypot(x - (ex + side * (rx * 0.9 + k * 0.9)), y - (lt - k * 0.9)) - 0.15) * 0.85);
      // brow: a short bar above the eye; tilt raises the inner end, asymmetry raises the right brow
      const bx = (x - ex) / 4.2;
      if (Math.abs(bx) <= 1) {
        const inner = side < 0 ? bx : -bx;            // +1 at the end nearest the nose
        const by = ey - 5.6 + c.browY - (1 - bx * bx) * 0.8 - c.browTilt * inner * 1.1 - (side > 0 ? c.browAsym : 0)
                 - (c.eyeOpen - 1) * 2;                    // thin and arched
        v = Math.max(v, soft(Math.abs(y - by)) * 0.6);
      }
    }
    // mouth: corners lifted by smile; an open mouth is a lens between the upper and lower lip
    const mx = COLS / 2 + gx * 0.5, my = 19.5 + gy * 0.6;
    const hw = 3 + 6 * c.mouthW;
    const u = (x - mx) / hw;
    if (Math.abs(u) <= 1.08) {
      const k = 1 - u * u;
      const top = my + c.smile * 1.8 * k - c.smile * 0.9 - c.mouthOpen * 1.2 * k;
      const bot = top + Math.max(0, c.mouthOpen) * 4.2 * Math.sqrt(Math.max(0, k)) ;
      if (c.mouthOpen > 0.12) {
        const inside = y >= top - 0.5 && y <= bot + 0.5 && Math.abs(u) <= 1;
        const edge = Math.min(Math.abs(y - top), Math.abs(y - bot));
        v = Math.max(v, inside ? Math.max(0.55, soft(edge - 0.2)) : soft(edge - 0.2) * (Math.abs(u) <= 1 ? 1 : 0));
      } else {
        v = Math.max(v, soft(Math.abs(y - top) - 0.25) * (Math.abs(u) <= 1 ? 1 : soft((Math.abs(u) - 1) * hw)));
        // closed lips: a soft, shorter lower lip under the line
        if (Math.abs(u) < 0.6) v = Math.max(v, soft(Math.abs(y - (top + 1.3 + 0.3 * (1 - u * u / 0.36)))) * 0.45);
      }
    }
    return v;
  }

  function draw() {
    if (!ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const fx = Math.floor((cols - COLS) / 2), fy = Math.floor((rows - ROWS) / 2);
    const rad = pitch * 0.36;
    for (let j = 0; j < rows; j++) {
      for (let i = 0; i < cols; i++) {
        const v = shade(i - fx + 0.5, j - fy + 0.5);
        const px = offX + (i + 0.5) * pitch, py = offY + (j + 0.5) * pitch;
        if (v < 0.04) {
          ctx.fillStyle = "rgba(56,189,248,0.07)";
        } else if (v > 0.8) {
          ctx.fillStyle = "#e6f8ff";
        } else {
          ctx.fillStyle = `rgba(56,189,248,${0.25 + v * 0.75})`;
        }
        ctx.beginPath();
        ctx.arc(px, py, v < 0.04 ? rad * 0.8 : rad, 0, Math.PI * 2);
        ctx.fill();
      }
    }
  }

  // --- what TTSController calls ---

  function show() {
    if (!mount()) return;
    clearTimeout(hideTimer); clearTimeout(warmTimer);
    nodStart = 0;
    if (visible && el.classList.contains("is-on")) return;
    const composer = el.parentElement && el.parentElement.querySelector(".code-mobile-composer");
    if (composer) el.style.setProperty("--ray-face-bottom", `${composer.offsetHeight + 10}px`);
    target = {...EXPR.neutral};
    el.hidden = false;
    visible = true;
    layout();
    nextBlink = performance.now() + 1500;
    requestAnimationFrame(() => el.classList.add("is-on"));
    kick();
  }

  // a chunk starts playing
  function say(text, rate = 1) {
    show();
    const p = plan(text);
    line = {text, times: p.times, track: p.track, sentences: p.sentences, total: p.total, rate: rate || 1,
            start: performance.now(), anchorIdx: 0, anchorT: 0};
    paused = 0;
  }

  // the browser reports the word at charIndex starting now
  function boundary(charIndex) {
    if (!line || charIndex == null || charIndex >= line.text.length) return;
    const now = performance.now();
    line.anchorIdx = charIndex;
    line.anchorT = (now - line.start) / 1000 * line.rate / speed;
  }

  // a chunk finished: learn how far off the estimate was, and close the mouth
  function chunkEnd() {
    if (!line) return;
    const real = (performance.now() - line.start) / 1000 * line.rate;
    if (line.total > 0.6 && real > 0.3) speed = Math.max(0.6, Math.min(1.8, speed * 0.6 + (real / line.total) * 0.4));
    line = null;
  }

  function pause(on) {
    if (!line) { paused = on ? 1 : 0; return; }
    if (on && !paused) { paused = 1; pauseAt = performance.now(); }
    else if (!on && paused) { paused = 0; line.start += performance.now() - pauseAt; }
  }

  // Ray stopped talking: a warm look and a small nod, then the panel fades out
  function end(finished = true) {
    if (!visible || !el) return;
    line = null;
    target = {...EXPR.warm};
    mouthTarget = VIS.sil;
    nodStart = performance.now();
    clearTimeout(warmTimer); clearTimeout(hideTimer);
    warmTimer = setTimeout(() => {
      el.classList.remove("is-on");
      hideTimer = setTimeout(() => {
        el.hidden = true;
        visible = false;
        nodStart = 0;
      }, reduced() ? 0 : FADE_OUT);
    }, finished ? WARM_MS : WARM_MS / 2);
  }

  window.addEventListener("resize", () => { if (visible) layout(); });
  return {show, say, boundary, chunkEnd, pause, end, moodOf, get visible() { return visible; }, get state() { return {...cur}; },
          set onStop(fn) { onStop = fn; }};
})();
