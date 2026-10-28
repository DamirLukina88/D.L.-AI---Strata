// serve/web/rayface.js - Ray as a little red panda drawn in dots, sitting at the left on the top edge of the Code tab's input box
// while he thinks about a spoken prompt or reads a reply aloud.  There is no window around him: only his own dots are
// drawn, and he fades in quickly and out slowly.
//
// A few colours only: oranges, browns, a warm white and a dark navy for the eyes and nose, with a one-dot dark outline
// (so he keeps an edge on the light theme) and a solid backing in the page colour (so nothing shows through between
// his dots).  The feed keeps room at its bottom while he is there.  The question marks fade in the display's blue.  He carries the voice through motion, not a talking mouth (a mouth that copies speech read
// as uncanny in every earlier version), following character-animation practice:
//   - squash and stretch on syllables, keeping volume; a small nod on stressed syllables (ease in and out)
//   - a blink when a thought ends (a pause after speech), and a gaze change hidden inside that blink
//   - a settle with a little overshoot after each sentence (follow-through)
//   - ears and tail that move a beat after the head (overlapping, secondary action); one ear more than the other
//   - a moving hold: breathing, a slow tail sway and a rare ear twitch, never fully still
//   - moods from simple rules on each sentence: happy eyes, a curious tilt, soft worry with drooping ears
//   - the mouth opens only on the strongest syllables (an accent), otherwise it is his small closed frown
//   - thinking: a paw on his chin, eyes up and to the side, question marks rising; the paw drops when he speaks
// Server voice (Web Audio): the motion follows the voice's loudness, read about 50 ms before it is heard
// (TTSController delays the output).  Browser voice: a loudness estimated from the text.  Clicking stops (onStop).
"use strict";

const RayFace = (() => {
  const COLS = 46, ROWS = 40;                 // the drawing's grid: head on top, body, feet and tail below
  const FADE_OUT = 700, WARM_MS = 1800;
  const C = {
    rim: "rgba(56,189,248,0.45)",
    orange: "#e8834e", light: "#f4a46e", shade: "#c8673a", paw: "#9a6038", brown: "#7a4a2e", dark: "#4a2c1d",
    white: "#f6efe4", navy: "#17213b", blush: "#e9967a", edge: "#3a2216", edgeLight: "#c9a682",
  };

  // moods: eye size, happy squint (0-1), ear lift (+ up, - droop), head tilt, gaze; used at 60% and held 2 s
  const EXPR = {
    neutral:   {eye: 1,    happy: 0.1,  ears: 0,    tilt: 0,     lookX: 0,    lookY: 0},
    happy:     {eye: 1,    happy: 0.6,  ears: 0.3,  tilt: 0,     lookX: 0,    lookY: 0},
    excited:   {eye: 1.12, happy: 0.35, ears: 0.6,  tilt: 0,     lookX: 0,    lookY: -0.2},
    surprised: {eye: 1.25, happy: 0,    ears: 0.8,  tilt: 0,     lookX: 0,    lookY: -0.2},
    curious:   {eye: 1.06, happy: 0.05, ears: 0.3,  tilt: 0.09,  lookX: 0.4,  lookY: -0.2},
    thinking:  {eye: 0.95, happy: 0,    ears: 0.1,  tilt: -0.05, lookX: -0.6, lookY: -0.6},
    concerned: {eye: 0.92, happy: 0,    ears: -0.6, tilt: 0,     lookX: 0,    lookY: 0.4},
    warm:      {eye: 1,    happy: 1,    ears: 0.2,  tilt: 0,     lookX: 0,    lookY: 0.1},
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
  const calm = (name) => {
    const e = EXPR[name], n = EXPR.neutral, out = {};
    for (const k of Object.keys(n)) out[k] = n[k] + (e[k] - n[k]) * 0.6;
    return out;
  };

  // a spring towards a target; damping below 1 gives a small overshoot and settle
  function spring(o, key, to, k, d) {
    const vk = key + "_v";
    o[vk] = ((o[vk] || 0) + (to - o[key]) * k) * d;
    o[key] += o[vk];
  }

  // ---------------------------------------------------------------------------------------------------------------
  // the red panda, as a colour per grid cell (null where nothing is drawn).  A pose:
  //   dy, rot, sx, sy (head transform about the neck), blink (0-1), eye (size), happy (0-1), lookX/Y, ears (both
  //   lift, + up, - droop), earL/earR (each ear's extra lift), mouth (0-1 open), paw (0-1: the paw raised to the
  //   chin), breath (-1..1), tail (sway angle)
  const newPose = () => ({dy: 0, rot: 0, sx: 1, sy: 1, blink: 0, eye: 1, happy: 0.1, lookX: 0, lookY: 0,
                          ears: 0, earL: 0, earR: 0, mouth: 0, paw: 0, tilt: 0, breath: 0, tail: 0});
  const inEll = (x, y, cx, cy, rx, ry) => ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2;

  // the head, in its own coordinates: centre (22, 14.6), chin near y 24
  function headCell(hx, hy, s) {
    const hd = inEll(hx, hy, 22, 14.6, 14, 9.6);
    if (hd < 1) {
      for (const side of [-1, 1]) {
        const ex = 22 + side * 7.6 + s.lookX * 0.8, ey = 13.6 + s.lookY * 0.6;
        // white brow marks above the eyes, slanted (outer end higher), lifting with the ears
        const bxc = 22 + side * 7.4, byc = 9.4 - s.ears * 0.5 - (side > 0 ? s.earR : s.earL) * 0.4;
        if (inEll(hx, hy + (hx - bxc) * side * 0.3, bxc, byc, 2, 1.1) < 1) return C.white;
        // eyes: large round navy dots with a small white highlight; a happy squint turns them into soft arcs
        const r = 2.15 * s.eye, ry = Math.max(0.4, r * (1 - s.blink) * (1 - 0.5 * s.happy));
        if (s.happy > 0.55 && s.blink < 0.5) {
          const ar = Math.hypot((hx - ex) / 2.2, (hy - (ey + 1.2)) / 1.9);
          if (hy < ey + 1.1 && Math.abs(ar - 1) < 0.38) return C.navy;
        } else if (inEll(hx, hy, ex, ey + s.happy * 0.5, r, ry) < 1) {
          if (s.blink < 0.5 && s.eye > 0.6 && inEll(hx, hy, ex - 0.8 + s.lookX * 0.3, ey - 0.9, 0.6, 0.6) < 1) return C.white;
          return C.navy;
        }
      }
      // nose, a short line down from it, and a small frown; the frown opens only as an accent
      if (inEll(hx, hy, 22, 16.1, 1.55, 0.85) < 1) return C.navy;
      if (s.mouth > 0.15) {
        if (inEll(hx, hy, 22, 19.3, 1.1 + s.mouth * 0.5, 0.6 + s.mouth * 0.7) < 1) return C.navy;
        if (hy > 16.8 && hy < 18.4 && Math.abs(hx - 22) < 0.6) return C.navy;
      } else {
        if (hy > 16.8 && hy < 18.9 && Math.abs(hx - 22) < 0.6) return C.navy;
        if (hy >= 18.9 && hy < 20 && Math.abs(Math.abs(hx - 22) - 1.5) < 0.6) return C.navy;
      }
      // white muzzle, white cheek patches at the sides, a dusky blush between eye and cheek
      if (inEll(hx, hy, 22, 18.7, 5.6, 4.5) < 1) return C.white;
      for (const side of [-1, 1]) {
        if (inEll(hx, hy, 22 + side * 12.4, 18.6, 3.6, 4.2) < 1) return C.white;
        if (inEll(hx, hy, 22 + side * 10.6, 16.4, 1.6, 0.8) < 1) return C.blush;
      }
      if (hd > 0.72 && hy > 19) return C.shade;                 // the darker lower rim
      if (hd < 0.45 && hy < 9.5) return C.light;                // the lit top of the head
      return C.orange;
    }
    // a small tuft of darker fur on top of the head, right of centre
    if (hy > 3.6 && hy < 5.4 && hx > 24.2 && hx < 28.4 && ((hx - 24.2) % 1.4) < 0.9 - (5.4 - hy) * 0.25) return C.shade;
    // ears: big, white, rounded triangles leaning outward, with orange fur at their base
    for (const side of [-1, 1]) {
      const lift = s.ears + (side > 0 ? s.earR : s.earL);
      const bx = 22 + side * 10.4, by = 7.8;
      const a = side * (0.55 - lift * 0.2);                // lean outward; a droop leans them further out and down
      const ca = Math.cos(a), sa = Math.sin(a);
      const ux = (hx - bx) * ca + (hy - by) * sa, uy = -(hx - bx) * sa + (hy - by) * ca;   // ear space, tip up (-y)
      const h = 7 + lift * 0.8;
      if (uy < 1.5 && uy > -h) {
        const half = 4.1 * Math.sqrt(Math.max(0, 1 + uy / h)) + 0.3;   // a rounded tip
        if (Math.abs(ux) < half) return uy > -2.2 ? C.orange : C.white;
      }
    }
    return null;
  }

  // the tail: a thick curve from the hip out to the right and up, orange with dark rings, swaying about its root
  function tailCell(x, y, s) {
    const bx = 27.5, by = 34.5;
    let best = 1e9, bu = 0;
    for (let k = 0; k <= 24; k++) {
      const u = k / 24, a = s.tail * u;
      const tx = 11 * u, ty = -5.5 * u ** 1.4;               // the curve before sway
      const px = bx + tx * Math.cos(a) - ty * Math.sin(a), py = by + tx * Math.sin(a) + ty * Math.cos(a);
      const fur = 0.35 * Math.sin(Math.atan2(y - py, x - px) * 5 + u * 9);   // a tufted edge
      const d = Math.hypot(x - px, y - py) - (3.9 - 0.6 * u + fur);
      if (d < best) { best = d; bu = u; }
    }
    if (best > 0.15) return null;
    if (bu > 0.9) return C.dark;                              // a dark tip
    return Math.floor(bu * 5 + 0.5) % 2 ? C.dark : C.orange;
  }

  // the whole panda: head (with its own nod, tilt and squash about the neck), body, arms, feet and tail
  function pandaCell(x, y, s) {
    // the raised paw is in front of everything
    const pawX = 15.6 + s.paw * 2.6, pawY = 31.8 - s.paw * 8.8;
    if (s.paw > 0.05) {
      const pd = inEll(x, y, pawX, pawY + s.dy * 0.5, 2.8, 2.2);
      if (pd < 1) return pd > 0.6 ? C.brown : C.paw;
      // the forearm from the shoulder up to the paw
      const ax = 14.6, ay = 30, vx = pawX - ax, vy = pawY - ay, len = Math.hypot(vx, vy) || 1;
      const t = Math.max(0, Math.min(1, ((x - ax) * vx + (y - ay) * vy) / (len * len)));
      if (Math.hypot(x - ax - vx * t, y - ay - vy * t) < 2.3) return C.paw;
    }
    // the head: grid -> head space (head centre 22, 14.6 sits at 21, 15.5), undoing nod, tilt and squash
    let px = x - 21, py = y - 24.9 - s.dy - s.breath * 0.25;
    const c = Math.cos(-s.rot), sn = Math.sin(-s.rot);
    [px, py] = [px * c - py * sn, px * sn + py * c];
    const head = headCell(px / s.sx + 22, py / s.sy + 24, s);
    if (head) return head;
    // feet, forward at the bottom, with light pads
    for (const side of [-1, 1]) {
      const fx = 21 + side * 5.6, fy = 37.4;
      if (inEll(x, y, fx, fy, 3.4, 2.3) < 1) {
        if (inEll(x, y, fx, fy + 0.6, 1.4, 0.8) < 1) return C.light;           // the big pad
        if (inEll(x, y, fx + side * 1.6, fy - 0.7, 0.6, 0.5) < 1) return C.light; // a toe
        return C.paw;
      }
    }
    // arms resting on the belly (the left one only while it is not raised)
    for (const side of [-1, 1]) {
      if (side < 0 && s.paw > 0.05) continue;
      const ad = inEll(x, y, 21 + side * 6.4, 30.4 + s.breath * 0.1, 2.5, 3.6);
      if (ad < 1) return ad > 0.62 ? C.dark : C.paw;
    }
    // the body: brown, darker at its edge, breathing
    const by = 31.2 - s.breath * 0.15;
    const bd = inEll(x, y, 21, by, 10.2, 7 * (1 + s.breath * 0.02));
    const tuft = 0.07 * Math.sin(Math.atan2(y - by, x - 21) * 11);              // fur at the edge
    if (bd < 1 + tuft) return bd > 0.82 + tuft ? C.dark : C.brown;
    return tailCell(x, y, s);
  }

  // a small "?" (5 x 7 dots) for the thinking pose
  const QMARK = ["01110", "10001", "00001", "00110", "00100", "00000", "00100"];
  function qmarkCell(x, y, ox, oy) {
    const cx = Math.floor(x - ox), cy = Math.floor(y - oy);
    return cy >= 0 && cy < 7 && cx >= 0 && cx < 5 && QMARK[cy][cx] === "1";
  }

  // ---------------------------------------------------------------------------------------------------------------
  let el = null, canvas = null, g = null, raf = 0, visible = false, hideTimer = 0, warmTimer = 0, onStop = null;
  const geo = {pitch: 3, cols: COLS, rows: ROWS, offX: 0, offY: 0, laidW: 0, laidH: 0};
  const pose = newPose();
  let target = calm("neutral");
  let level = 0, paused = false, mode = "idle";   // "think" | "audio" | "text" | "warm" | "idle"
  let analyser = null, tbuf = null;
  let line = null;                            // the chunk being spoken: {text, times[], amp[], sentences[], total, …}
  let audioText = null, audioStart = 0, audioDur = 0, audioCtx = null;
  let speed = 1, thinkAt = 0;
  let mood = "neutral", moodAt = 0;
  const mem = {lastLoud: 0, wasTalking: false, stressAt: -1e9, prevL: 0, blinkAt: -1e9, nextIdleBlink: 0,
               glance: {x: 0, y: 0}, glanceNext: {x: 0, y: 0}, settleAt: -1e9, twitchAt: 0, twitchStart: -1e9, twitchSide: 1};

  function setMood(name, now) {
    if (name === mood || now - moodAt < 2000) return;
    mood = name; moodAt = now;
    target = calm(name);
  }

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

  // fit the dot grid to the canvas's size (once per size change); the drawing sits on the canvas's bottom edge
  function layout() {
    const r = canvas.getBoundingClientRect();
    if (!r.width || !r.height || (r.width === geo.laidW && r.height === geo.laidH)) return;
    geo.laidW = r.width; geo.laidH = r.height;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(r.width * dpr);
    canvas.height = Math.round(r.height * dpr);
    geo.pitch = Math.min(canvas.width / COLS, canvas.height / ROWS);
    geo.offX = (canvas.width - COLS * geo.pitch) / 2;
    geo.offY = canvas.height - ROWS * geo.pitch;
  }

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

  // the voice's loudness now, 0-1, with a noise gate (speech is about 0.02-0.2 RMS)
  function readAudio() {
    const n = analyser.fftSize;
    if (!tbuf || tbuf.length !== n) tbuf = new Float32Array(n);
    analyser.getFloatTimeDomainData(tbuf);
    let sum = 0;
    for (let i = 0; i < n; i++) sum += tbuf[i] * tbuf[i];
    return Math.max(0, Math.min(1, (Math.sqrt(sum / n) - 0.012) / 0.14));
  }

  // the motion, from the loudness and the clock
  function step(now) {
    let loud = 0;
    if (!paused && mode === "audio" && analyser) {
      loud = readAudio();
      if (audioText && audioDur > 0) {
        const i = charAt(audioText, (audioCtx.currentTime - audioStart) / audioDur * audioText.total);
        const sen = audioText.sentences.find((s) => i >= s.from && i <= s.to);
        if (sen) setMood(sen.mood, now);
      }
    } else if (!paused && mode === "text" && line) {
      const i = charAt(line, line.times[line.anchorIdx] + (now - line.start) / 1000 * line.rate / speed - line.anchorT);
      if (i < line.text.length) {
        loud = line.amp[i];
        const sen = line.sentences.find((s) => i >= s.from && i <= s.to);
        if (sen) setMood(sen.mood, now);
      }
    }
    level += (loud - level) * (loud > level ? 0.3 : 0.1);
    const talking = mode === "audio" || mode === "text", think = mode === "think";

    // a stressed syllable: the loudness rising past 0.72
    if (level > 0.72 && mem.prevL <= 0.72 && now - mem.stressAt > 260) mem.stressAt = now;
    mem.prevL = level;
    if (level > 0.08) { mem.lastLoud = now; mem.wasTalking = true; }
    // a thought ends: quiet for 280 ms after speech -> a settle, a blink, and sometimes a new gaze inside the blink
    if (mem.wasTalking && now - mem.lastLoud > 280) {
      mem.wasTalking = false;
      mem.settleAt = now;
      if (now - mem.blinkAt > 900) {
        mem.blinkAt = now;
        if (Math.random() < 0.45) mem.glanceNext = Math.random() < 0.5 ? {x: 0, y: 0} : {x: (Math.random() - 0.5) * 0.9, y: -Math.random() * 0.3};
      }
    }
    // a moving hold: a rare blink in long stillness, an occasional ear twitch
    if (now > mem.nextIdleBlink && now - mem.blinkAt > 4200) { mem.blinkAt = now; mem.nextIdleBlink = now + 4500 + Math.random() * 3000; }
    if (now > mem.twitchAt) { mem.twitchAt = now + 3500 + Math.random() * 4000; mem.twitchSide = Math.random() < 0.5 ? -1 : 1; mem.twitchStart = now; }

    // blink: 120 ms closing, 60 ms closed, 180 ms opening (large eyes blink slowly); the gaze moves while closed
    const bt = now - mem.blinkAt;
    pose.blink = bt < 120 ? bt / 120 : bt < 180 ? 1 : bt < 360 ? 1 - (bt - 180) / 180 : 0;
    if (bt > 120 && bt < 180) mem.glance = mem.glanceNext;

    const stressK = Math.exp(-(now - mem.stressAt) / 220);           // 1 right at a stressed syllable, then fades
    const settleK = now - mem.settleAt < 260 ? 1 : 0;                 // a short push that the spring overshoots
    pose.breath = Math.sin(now / 1000 * Math.PI * 2 / 4.2);           // a 4.2 s breath
    const tw = now - mem.twitchStart;
    const twitch = tw >= 0 && tw < 260 ? Math.sin(tw / 260 * Math.PI) : 0;
    const t = (now - thinkAt) / 1000;

    // thinking: paw to the chin, eyes up and to the side, drifting; a small slow tilt
    const tgt = think ? {...target, lookX: 0.7 + 0.25 * Math.sin(t / 2.4), lookY: -0.75, tilt: -0.06 + 0.03 * Math.sin(t / 3.1)} : target;
    spring(pose, "paw", think ? 1 : 0, 0.08, 0.75);

    // squash and stretch (volume kept), the nod, the settle
    spring(pose, "sy", 1 - 0.035 * level, 0.25, 0.62);
    pose.sx = 1 / pose.sy;
    spring(pose, "dy", 0.7 * stressK + 0.55 * settleK, 0.14, 0.74);
    // mood, eased slowly; ears and tail follow a beat later, with an extra flick on stresses
    for (const k of ["eye", "happy", "tilt"]) spring(pose, k, tgt[k] + (k === "happy" && talking ? 0.25 * stressK : 0), 0.05, 0.8);
    spring(pose, "rot", pose.tilt, 0.06, 0.8);
    spring(pose, "ears", tgt.ears, 0.04, 0.82);
    spring(pose, "earL", 0.18 * stressK + (mem.twitchSide < 0 ? 0.5 * twitch : 0), 0.18, 0.68);
    spring(pose, "earR", 0.25 * stressK + (think ? 0.2 : 0) + (mem.twitchSide > 0 ? 0.5 * twitch : 0), 0.18, 0.68);
    spring(pose, "tail", 0.1 * Math.sin(now / 1600) - 0.12 * Math.exp(-(now - mem.stressAt - 120) / 300) * (now > mem.stressAt + 120 ? 1 : 0), 0.05, 0.85);
    spring(pose, "lookX", tgt.lookX + mem.glance.x, 0.08, 0.8);
    spring(pose, "lookY", tgt.lookY + mem.glance.y, 0.08, 0.8);
    // the mouth: only an accent on the strongest syllables
    spring(pose, "mouth", talking && level > 0.8 ? 0.4 + 0.6 * stressK : 0, 0.3, 0.6);
  }

  // the page colour behind him (read again now and then, so a theme switch follows).  The gaps between his dots take a
  // darker shade of each dot's own colour and the dots are large, so he stays solid and saturated instead of washed out
  // by white gaps or sunk into dark ones; his outline is dark on a light page and light tan on a dark one
  let bgAt = 0, lightPage = false;
  const shadeCache = {};
  function deeper(hex) {
    if (!shadeCache[hex]) {
      const n = parseInt(hex.slice(1), 16), f = 0.8;
      shadeCache[hex] = `rgb(${((n >> 16) & 255) * f | 0},${((n >> 8) & 255) * f | 0},${(n & 255) * f | 0})`;
    }
    return shadeCache[hex];
  }
  const cells = new Array(COLS * ROWS);
  function draw(now) {
    if (now - bgAt > 500) {
      bgAt = now;
      const c = el.parentElement && getComputedStyle(el.parentElement).backgroundColor;
      if (c && c !== "rgba(0, 0, 0, 0)" && c !== "transparent") {
        const m = c.match(/\d+/g);
        lightPage = m ? (0.299 * m[0] + 0.587 * m[1] + 0.114 * m[2]) / 255 > 0.5 : false;
      }
    }
    g.clearRect(0, 0, canvas.width, canvas.height);
    const P = geo.pitch, rad = P * 0.47, EDGE = lightPage ? C.edge : C.edgeLight;
    for (let j = 0; j < ROWS; j++) for (let i = 0; i < COLS; i++) cells[j * COLS + i] = pandaCell(i + 0.5, j + 0.5, pose);
    // a one-dot outline around his shape, so he keeps an edge on any page
    for (let j = 0; j < ROWS; j++) {
      for (let i = 0; i < COLS; i++) {
        const k = j * COLS + i;
        if (cells[k]) continue;
        let near = false;
        for (let dj = -1; dj <= 1 && !near; dj++) for (let di = -1; di <= 1 && !near; di++) {
          const ii = i + di, jj = j + dj;
          const c = ii >= 0 && ii < COLS && jj >= 0 && jj < ROWS ? cells[jj * COLS + ii] : null;
          if (c && c !== EDGE) near = true;
        }
        if (near) cells[k] = EDGE;
      }
    }
    // a solid silhouette behind the dots, so nothing behind him shows through the gaps
    for (let j = 0; j < ROWS; j++) {
      for (let i = 0; i < COLS; i++) {
        const c = cells[j * COLS + i];
        if (!c) continue;
        g.fillStyle = deeper(c);
        g.fillRect(geo.offX + i * P - 0.5, geo.offY + j * P - 0.5, P + 1, P + 1);
      }
    }
    for (let j = 0; j < ROWS; j++) {
      for (let i = 0; i < COLS; i++) {
        const col = cells[j * COLS + i];
        if (!col) continue;
        g.fillStyle = col;
        g.beginPath();
        g.arc(geo.offX + (i + 0.5) * P, geo.offY + (j + 0.5) * P, rad, 0, Math.PI * 2);
        g.fill();
      }
    }
    // while thinking, a question mark every 2.6 s rises beside his head and fades (no outline, no backing)
    const qt = ((now - thinkAt) / 1000 % 2.6) / 2.6, qa = pose.paw > 0.5 ? Math.sin(Math.PI * qt) : 0, qy = 3 - qt * 2;
    if (qa > 0.25) {
      g.fillStyle = qa > 0.6 ? C.white : C.rim;
      for (let j = 0; j < ROWS; j++) {
        for (let i = 34; i < COLS; i++) {
          if (!qmarkCell(i + 0.5, j + 0.5, 39.5, qy)) continue;
          g.beginPath();
          g.arc(geo.offX + (i + 0.5) * P, geo.offY + (j + 0.5) * P, rad, 0, Math.PI * 2);
          g.fill();
        }
      }
    }
  }

  // while he is there, the feed keeps room at its bottom so the last message stays above him
  function makeRoom(on) {
    const view = el && el.parentElement, feed = view && view.querySelector(".code-mobile-messages");
    if (!feed) return;
    const atEnd = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 48;
    view.classList.toggle("ray-room", on);
    if (on && atEnd) feed.scrollTop = feed.scrollHeight;
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

  // where he sits: at the left, his feet on the top edge of the input box
  function place() {
    const composer = el.parentElement && el.parentElement.querySelector(".code-mobile-composer");
    if (composer) el.style.setProperty("--ray-face-bottom", `${composer.offsetHeight - 3}px`);
  }

  function show() {
    if (!mount()) return;
    clearTimeout(hideTimer); clearTimeout(warmTimer);
    if (visible && el.classList.contains("is-on")) return;
    place();
    mood = "neutral"; moodAt = 0; target = calm("neutral");
    const now = performance.now();
    // anticipation: he arrives a little stretched and raised, and settles
    Object.assign(pose, newPose(), {dy: -1.2, sy: 1.06, sx: 1 / 1.06, earL: 0.4, earR: 0.4});
    Object.assign(mem, {wasTalking: false, lastLoud: now, blinkAt: now - 2000, nextIdleBlink: now + 2500, stressAt: -1e9,
                        settleAt: -1e9, twitchAt: now + 2500, twitchStart: -1e9, glance: {x: 0, y: 0}, glanceNext: {x: 0, y: 0}});
    el.hidden = false;
    visible = true;
    makeRoom(true);
    layout();
    requestAnimationFrame(() => el.classList.add("is-on"));
    kick();
  }

  // --- what the web app calls ---

  // a spoken prompt is being answered: he appears in his thinking pose until he speaks (or the turn ends)
  function thinking() {
    if (mode === "audio" || mode === "text") return;   // already speaking
    show();
    mode = "think";
    thinkAt = performance.now();
    target = calm("neutral");
  }

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

  // Ray stopped talking (or the turn ended): happy eyes and a small nod that settles, then he fades out slowly
  function end(finished = true) {
    if (!visible || !el) return;
    line = null; analyser = null; audioText = null;
    mode = "warm";
    target = {...EXPR.warm};
    mood = "warm";
    mem.stressAt = performance.now();          // the nod
    clearTimeout(warmTimer); clearTimeout(hideTimer);
    warmTimer = setTimeout(() => {
      el.classList.remove("is-on");
      hideTimer = setTimeout(() => {
        el.hidden = true;
        visible = false;
        mode = "idle";
        makeRoom(false);
      }, FADE_OUT);
    }, finished ? WARM_MS : WARM_MS / 2);
  }

  window.addEventListener("resize", () => { if (visible) { place(); layout(); } });
  return {thinking, speakAudio, speakText, boundary, chunkEnd, pause, end, moodOf,
          get visible() { return visible; }, get state() { return {...pose, mode, level, mood}; },
          set onStop(fn) { onStop = fn; }};
})();
