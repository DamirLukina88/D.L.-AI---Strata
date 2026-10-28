// serve/web/rayface.js - Ray's talking face: a shaded blue portrait on a dot matrix, shown only while Ray reads a
// reply aloud.
// The browser's speech engine gives no audio to analyse, so the mouth follows the text: each word becomes mouth shapes
// (web/lipsync-en.js, TalkingHead's English rules) on an estimated timeline with pauses at spaces and punctuation;
// word-boundary events resync it where the browser sends them, and the speed is corrected from each chunk's real
// length. Expressions come from simple rules on each sentence. Clicking the face stops the speech (onStop).
"use strict";

const RayFace = (() => {
  const COLS = 36, ROWS = 46;                 // the face's own units (portrait); a wider panel shows dark dots around it
  const RES = 1.35;                           // dots per face unit
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
    neutral:   {eyeOpen: 1,    squint: 0,   browY: 0,    browTilt: 0,    browAsym: 0,   smile: 0.1,  lookX: 0,    lookY: 0},
    happy:     {eyeOpen: 0.95, squint: 0.5, browY: -0.3, browTilt: 0,    browAsym: 0,   smile: 0.7,  lookX: 0,    lookY: 0},
    excited:   {eyeOpen: 1.12, squint: 0.2, browY: -0.9, browTilt: 0,    browAsym: 0,   smile: 0.8,  lookX: 0,    lookY: -0.3},
    surprised: {eyeOpen: 1.3,  squint: 0,   browY: -1.3, browTilt: 0,    browAsym: 0,   smile: 0,    lookX: 0,    lookY: -0.2},
    curious:   {eyeOpen: 1.05, squint: 0,   browY: -0.3, browTilt: 0,    browAsym: 1,   smile: 0.2,  lookX: 0.6,  lookY: -0.2},
    thinking:  {eyeOpen: 0.85, squint: 0.1, browY: -0.1, browTilt: -0.3, browAsym: 0.7, smile: 0,    lookX: -1,   lookY: -0.8},
    concerned: {eyeOpen: 0.9,  squint: 0,   browY: 0.2,  browTilt: 0.9,  browAsym: 0,   smile: -0.4, lookX: 0,    lookY: 0.4},
    warm:      {eyeOpen: 0.75, squint: 0.7, browY: -0.2, browTilt: 0.2,  browAsym: 0,   smile: 0.85, lookX: 0,    lookY: 0.2},
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
    pitch = Math.min(r.width / (COLS + 2) / RES, r.height / (ROWS + 2) / RES) * dpr;
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

  // brightness 0-1 at grid cell (x, y), in face coordinates (0..COLS, 0..ROWS): an oval face lit from the front with a
  // light rim around it, almond eyes with glowing irises, a soft nose and lips; outside the rim it is 0 (dark dots)
  const CX = COLS / 2, TOP = 2.5, MID = 18, CHIN = 44.5, HALF = 11.6;
  function halfWidth(y) {                     // the face outline: round forehead, narrowing to a soft point at the chin
    if (y < TOP || y > CHIN) return 0;
    if (y <= MID) { const t = (MID - y) / (MID - TOP); return HALF * Math.sqrt(1 - t * t); }
    const t = (y - MID) / (CHIN - MID);
    return HALF * Math.sqrt(Math.max(0, 1 - Math.pow(t, 1.9))) * (1 - 0.3 * t);
  }
  const g2 = (dx, dy, sx, sy) => Math.exp(-((dx * dx) / (sx * sx) + (dy * dy) / (sy * sy)));
  function shade(x, y) {
    const c = cur;
    y -= c.nod * 1.2;
    const gx = c.lookX * 0.5, gy = c.lookY * 0.4;
    const w = halfWidth(y), ax = Math.abs(x - CX);
    // the shell: a white hood over the forehead and down the sides (open below the cheeks), lit at its inner edge and
    // parted from the face by a dark seam
    if (ax > w - 0.15 || !w) {
      const sTop = TOP - 2.6, sHalf = HALF + 2.8;
      let sw = 0;
      if (y >= sTop && y <= MID) { const t = (MID - y) / (MID - sTop); sw = sHalf * Math.sqrt(1 - t * t); }
      else if (y > MID && y < 36) sw = sHalf * (1 - 0.12 * (y - MID) / (36 - MID));
      const gap = w ? ax - w : (y < TOP ? (TOP - y) * 1.4 : 0);
      if (w && ax <= w + 0.6) return 0.05;                           // the seam
      if (!w && y >= TOP - 0.6 && y < TOP) return 0.05;
      if (!sw || ax > sw) return 0;
      const fade = y > 30 ? Math.max(0, 1 - (y - 30) / 6) : 1;
      return (0.62 + 0.3 * Math.exp(-gap / 1.6)) * fade;
    }
    const d = ax / w, lower = Math.max(0, (y - MID) / (CHIN - MID));
    // skin: brighter at the forehead and cheekbones, darker towards the edge, the jaw and in the eye sockets
    let v = 0.44 - 0.2 * d * d - 0.08 * d * lower;
    v += 0.1 * g2(x - CX, y - 10, 6, 4);
    v += (0.08 + 0.1 * Math.max(0, c.smile)) * g2(ax - 7.4, y - (27 - 0.8 * Math.max(0, c.smile)), 2.6, 2.2);
    for (const side of [-1, 1]) {
      const ex = CX + side * 5.6, ey = 21;
      v -= 0.2 * g2(x - ex, y - ey + 0.3, 4.2, 2.4);
      // brow ridge: a thin light line, raised by browY, tilted (inner end up) and one-sided for asymmetry
      const bu = (x - ex) / 4.3;
      if (Math.abs(bu) <= 1.1) {
        const inner = side < 0 ? bu : -bu;
        const by = ey - 3.8 + c.browY - (1 - bu * bu) * 0.7 - c.browTilt * inner * 0.9 - (side > 0 ? c.browAsym : 0)
                 - (c.eyeOpen - 1) * 1.5;
        v += 0.3 * g2(0, y - by, 1, 0.5) * (1 - Math.max(0, Math.abs(bu) - 0.8) * 3);
      }
      // almond eye: upper lid arched, outer corner a little higher; squint lifts the lower lid
      const u = (x - ex) / 3.8;
      if (Math.abs(u) < 1) {
        const k = 1 - u * u, open = Math.max(0, c.eyeOpen * (1 - c.blink));
        const tilt = -0.35 * u * side;
        const up = ey + tilt - 1.9 * open * Math.pow(k, 0.7);
        const lo = ey + tilt + (1 - 0.7 * c.squint) * Math.min(1, open) * k;
        const liner = 0.75 + 0.35 * Math.max(0, u * side);              // thicker towards the outer corner
        if (y >= up - liner && y <= up + 0.1) v = 0.06;                  // the upper lid line
        else if (y > up && y < lo) {
          const ix = ex + c.lookX * 1.1, iy = ey + 0.1 + c.lookY * 0.5;
          const r = Math.hypot(x - ix, (y - iy) * 1.1);
          v = r < 1.3 ? 1 : r < 1.9 ? 0.7 : 0.3;                        // iris glow, then the white of the eye
        } else if (y >= lo && y < lo + 0.7) v -= 0.1;
        // the liner flicks up and out past the outer corner
      } else if (u * side > 0 && u * side < 1.35) {
        const wy = ey - 0.35 * side * side - (u * side - 1) * 1.4 - 0.4;
        if (Math.abs(y - wy) < 0.45 * (1.35 - u * side) / 0.35) v = 0.06;
      }
    }
    // nose: a light bridge, a bright tip, dark nostrils and a shadow under it
    if (y > 22.5 && y < 30.5) v += 0.14 * g2(x - CX - 0.3, 0, 0.6, 1);
    v -= 0.1 * g2(x - CX + 1.5, y - 28, 0.7, 2.5);
    v += 0.22 * g2(x - CX, y - 30.9, 1.1, 0.8);
    for (const side of [-1, 1]) v -= 0.3 * g2(x - CX - side * 1.2, y - 32.2, 0.6, 0.45);
    v -= 0.1 * g2(x - CX, y - 33.4, 1.8, 0.55);
    // lips: corners lifted by smile; opening parts them; the lower lip is fuller and catches the light
    const mx = CX + gx * 0.3, my = 36.6 + gy * 0.3;
    const hw = 2.9 + 2.4 * c.mouthW;
    const mu = (x - mx) / hw;
    if (Math.abs(mu) < 1) {
      const k = 1 - mu * mu;
      const mid = my - c.smile * 0.7 + c.smile * 1.2 * k;
      const gap = Math.max(0, c.mouthOpen) * 2.8 * Math.sqrt(k);
      const upTop = mid - gap / 2 - 1.3 * Math.pow(k, 0.6) + 0.45 * g2(x - mx, 0, 0.9, 1);
      const upBot = mid - gap / 2, loTop = mid + gap / 2, loBot = loTop + 1.9 * Math.pow(k, 0.8);
      if (y > upBot - 0.4 && y < loTop + 0.4) v = gap > 0.4 ? 0.04 : 0.08;  // the line between the lips, or the mouth
      else if (y >= upTop && y <= upBot) v = 0.62;
      else if (y >= loTop && y <= loBot) v = 0.66 + 0.3 * g2(x - mx, y - (loTop + loBot) / 2 + 0.2, 1.6, 0.5);
      else if (y > loBot && y < loBot + 0.8) v -= 0.1;                  // the shadow under the lower lip
    }
    v += 0.06 * g2(x - CX, y - 41.3, 2, 1);                             // chin
    return Math.max(0.06, Math.min(1, v));
  }

  function draw() {
    if (!ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const fx = (cols - COLS * RES) / 2, fy = (rows - ROWS * RES) / 2;
    const rad = pitch * 0.4;
    for (let j = 0; j < rows; j++) {
      for (let i = 0; i < cols; i++) {
        const v = shade((i - fx + 0.5) / RES, (j - fy + 0.5) / RES);
        const px = offX + (i + 0.5) * pitch, py = offY + (j + 0.5) * pitch;
        if (v < 0.04) {
          ctx.fillStyle = "rgba(56,189,248,0.07)";
        } else if (v > 0.8) {
          ctx.fillStyle = "#e6f8ff";
        } else {
          ctx.fillStyle = `rgba(56,189,248,${0.12 + v * 0.95})`;
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
