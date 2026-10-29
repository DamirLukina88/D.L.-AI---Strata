// serve/web/rayface.js - Ray as a little red panda drawn in dots, sitting at the left on the top edge of the Code tab's input box
// while the model works or he reads a reply aloud.  There is no window around him: only his own dots are
// drawn, and he fades in quickly and out slowly.
//
// A few colours only: oranges, browns, a warm white and a dark navy for the eyes and nose.  The gaps between his dots
// are filled (so nothing shows through), and on the light theme a thin dark line follows his edge.  The feed keeps room at its bottom while he is there.  The question marks fade in the display's blue.  He carries the voice through motion, not a talking mouth (a mouth that copies speech read
// as uncanny in every earlier version), following character-animation practice:
//   - squash and stretch on syllables, keeping volume; a small nod on stressed syllables (ease in and out)
//   - a blink when a thought ends (a pause after speech), and a gaze change hidden inside that blink
//   - a settle with a little overshoot after each sentence (follow-through)
//   - ears and tail that move a beat after the head (overlapping, secondary action); one ear more than the other
//   - a moving hold: breathing, a slow tail sway and a rare ear twitch, never fully still
//   - moods from simple rules on each sentence: happy eyes, a curious tilt, soft worry with drooping ears
//   - the mouth opens only on the strongest syllables (an accent), otherwise it is his small closed frown
//   - thinking: a paw on his chin, eyes up and to the side, question marks rising; the paw drops when he speaks
//   - a cocoa break now and then while thinking: after 8 s of a think, a 1 in 3 chance (never on two thinks in a row) that a
//     white mug of hot chocolate appears beside him on the input box; he holds it in both paws and sips with closed eyes,
//     in one of four styles picked at random (never the same twice running): classic, slow savour, too hot, sips while
//     thinking.  Speech or the answer arriving takes the mug away at once
//   - on a long task (30 s into the turn, or 6 tool calls) he works at something, picked at random for each round from
//     what fits the work (weights in POOLS): a blueprint, calipers on a printed cube, a notepad of equations, a Rubik's
//     cube.  The newest kind of work counts; there is only ever one prop, and a round always finishes before the next
// Server voice (Web Audio): the motion follows the voice's loudness, read about 50 ms before it is heard
// (TTSController delays the output).  Browser voice: a loudness estimated from the text.  Clicking stops (onStop).
"use strict";

const RayFace = (() => {
  const COLS = 46, ROWS = 40;                 // the drawing's grid: head on top, body, feet and tail below
  const FADE_OUT = 700, WARM_MS = 1800;
  const C = {
    rim: "rgba(56,189,248,0.45)",
    orange: "#e8834e", light: "#f4a46e", shade: "#c8673a", paw: "#9a6038", brown: "#7a4a2e", dark: "#4a2c1d",
    white: "#f6efe4", navy: "#17213b", blush: "#e9967a", edge: "#3a2216",
    cocoa: "#5a3220", mugShade: "#d8c9b6", mugRim: "#fffaf2", mugHi: "#ffffff", tongue: "#f08a9a",
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
  //   glow (0-1: warmer cheeks); during a cocoa break: cup ({x, y, sc} or null) and pawL/pawR (grid points, or null
  //   for the usual arms)
  const newPose = () => ({dy: 0, rot: 0, sx: 1, sy: 1, blink: 0, eye: 1, happy: 0.1, lookX: 0, lookY: 0,
                          ears: 0, earL: 0, earR: 0, mouth: 0, paw: 0, tilt: 0, breath: 0, tail: 0, glow: 0,
                          cup: null, pawL: null, pawR: null, tongue: 0, work: null});
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
      // concentration: the tip of his tongue at the corner of his mouth
      if (s.tongue > 0.5 && inEll(hx, hy, 23.6, 20.6, 0.95, 0.8) < 1) return C.tongue;
      if (inEll(hx, hy, 22, 18.7, 5.6, 4.5) < 1) return C.white;
      for (const side of [-1, 1]) {
        if (inEll(hx, hy, 22 + side * 12.4, 18.6, 3.6, 4.2) < 1) return C.white;
        if (inEll(hx, hy, 22 + side * 10.6, 16.4, 1.6 + s.glow * 0.5, 0.8 + s.glow * 0.3) < 1) return C.blush;
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
    // during a cocoa break: dark paws, then the mug, then the forearms, all in front of him
    if (s.pawL || s.pawR || s.cup || s.work) {
      for (const p of [s.pawL, s.pawR]) {
        if (!p) continue;
        const pd = inEll(x, y, p.x, p.y + s.dy * 0.3, 2.4, 2.1);
        if (pd < 1) return pd > 0.5 ? C.dark : C.brown;
      }
      const key = Math.floor(y) * COLS + Math.floor(x), w = s.work;
      if (w && w.front.has(key)) return w.front.get(key);           // a pencil or calipers in his paw
      const mug = mugCell(x, y, s.cup);
      if (mug) return mug;
      const r = w ? 1.8 : 2.2;                                       // slimmer while he works, so the work shows
      const arm = (s.pawL && armCell(x, y, SH_L, s.pawL, r)) || (s.pawR && armCell(x, y, SH_R, s.pawR, r));
      if (arm) return arm;
      if (w && w.prop.has(key)) return w.prop.get(key);             // a sheet, a notepad, a cube, a printed part
      if (w && !s.pawL) {                                            // his other paw stays on his chin
        const pd = inEll(x, y, CHIN.x, CHIN.y + 0.8 + s.dy * 0.5, 2.8, 2.2);
        if (pd < 1) return pd > 0.6 ? C.brown : C.paw;
      }
    }
    // the raised paw is in front of everything
    const pawX = 15.6 + s.paw * 2.6, pawY = 31.8 - s.paw * 8.8;
    if (s.paw > 0.05 && !s.pawL) {
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
      if (side < 0 && (s.paw > 0.05 || s.pawL)) continue;
      if (side > 0 && s.pawR) continue;
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

  // the mug, on whole cells around its centre (9 x 8, a handle on the right) so it never shimmers as it moves.  In front
  // of him it has a dark edge, so the white mug still reads against his white muzzle
  function mugCore(lx, ly) {
    if ((lx === 5 && (ly === -3 || ly === 1)) || (lx === 6 && ly >= -2 && ly <= 0)) return C.white;   // the handle
    if (Math.abs(lx) > 4 || ly < -4 || ly > 3) return null;
    if (ly === 3 && Math.abs(lx) === 4) return null;                 // a rounded foot
    if (ly === -4) return Math.abs(lx) <= 3 ? C.cocoa : C.mugRim;    // cocoa at the rim
    if (lx === 4) return C.mugShade;
    if (lx === -3 && ly >= -3 && ly <= -1) return C.mugHi;          // a glint
    return C.white;
  }
  function mugCell(x, y, cup) {
    if (!cup || cup.sc < 0.08) return null;
    const lx = Math.round((x - cup.x) / cup.sc), ly = Math.round((y - cup.y) / cup.sc);
    const core = mugCore(lx, ly);
    if (core) return core;
    if (cup.y < 33 && cup.sc > 0.6 && (mugCore(lx - 1, ly) || mugCore(lx + 1, ly) || mugCore(lx, ly - 1) || mugCore(lx, ly + 1))) return C.edge;
    return null;
  }
  const SH_L = {x: 14.6, y: 29.6}, SH_R = {x: 27.4, y: 29.6};
  function armCell(x, y, sh, p, r = 2.2) {
    const vx = p.x - sh.x, vy = p.y - sh.y, len2 = vx * vx + vy * vy || 1;
    const t = Math.max(0, Math.min(1, ((x - sh.x) * vx + (y - sh.y) * vy) / len2));
    const d = Math.hypot(x - sh.x - vx * t, y - sh.y - vy * t);
    return d < r ? (d > r - 0.7 ? C.dark : C.paw) : null;
  }

  // ---------------------------------------------------------------------------------------------------------------
  // the cocoa break.  Places are grid cells: the mug rests on the input box at his tail side, comes to his chest, under
  // his chin or to his mouth; one paw fetches it from underneath, both hold it at the sides
  const BREAK_AFTER = 8000, BREAK_CHANCE = 1 / 3;
  const REST = {x: 37.5, y: 36.5}, CHEST = {x: 21.5, y: 28.5}, SNUG = {x: 21.5, y: 26.5}, MOUTH = {x: 21.5, y: 22.5};
  const CTRL = {x: 33, y: 25}, CHIN = {x: 18.2, y: 23}, PAW_R_REST = {x: 27.4, y: 31.4};
  const NEAR = {x: -5, y: 0.5}, UNDER = {x: 0.3, y: 4.8}, LEFT = {x: -5.3, y: 0.6}, RIGHT = {x: 5.3, y: 0.6};
  const ease = (t) => t * t * (3 - 2 * t);
  const lerp = (a, b, t) => a + (b - a) * t;
  const lerpP = (p, q, t) => ({x: p.x + (q.x - p.x) * t, y: p.y + (q.y - p.y) * t});
  const add = (p, o) => ({x: p.x + o.x, y: p.y + o.y});
  const bez = (p, c, q, t) => ({x: (1 - t) ** 2 * p.x + 2 * (1 - t) * t * c.x + t * t * q.x, y: (1 - t) ** 2 * p.y + 2 * (1 - t) * t * c.y + t * t * q.y});
  const backOut = (t) => { t -= 1; return t * t * (2.9 * t + 1.9) + 1; };
  const START = [["pop", 0.6], ["reach", 0.7], ["lift", 0.9], ["hold", 0.5]];
  const END = [["regrip", 0.45], ["down", 0.8], ["release", 0.5], ["fade", 0.5]];
  // the four styles, each a list of [phase, seconds]
  const STYLES = {
    classic: {script: [...START, ["raise", 0.6], ["sip", 1.4], ["lower", 0.5], ["ahh", 0.7], ["cosy", 1.1], ...END]},
    savour: {lowerTo: SNUG, sway: true, script: [["pop", 0.8], ["reach", 1.0], ["lift", 1.3], ["hold", 0.6], ["sniff", 1.8], ["raise", 0.8],
      ["sip", 1.6], ["lower", 0.6], ["sigh", 1.3], ["raise", 0.8], ["sip", 1.2], ["lower", 0.6], ["cosy", 1.4], ["regrip", 0.6],
      ["down", 1.0], ["release", 0.6], ["fade", 0.7]]},
    hot: {script: [...START, ["blow", 1.0], ["test", 0.35], ["hot", 0.8], ["blow", 1.0], ["raise", 0.6], ["sip", 1.3], ["lower", 0.5],
      ["ahh", 0.7], ["cosy", 0.6], ...END]},
    thinking: {script: [...START, ["thinkhold", 1.6], ["raise", 0.5], ["sip", 0.9], ["lower", 0.5], ["thinkhold", 1.8], ["raise", 0.5],
      ["sip", 0.9], ["lower", 0.5], ["thinkhold", 1.2], ...END]},
  };
  const MOVES = new Set(["lift", "raise", "test", "lower", "down", "hot", "sniff"]);
  const HELD = new Set(["blow", "raise", "sip", "test", "hot", "lower", "ahh", "cosy", "sniff", "sigh", "thinkhold"]);

  // the phases with their times and where the mug starts and ends each one
  function phasesOf(style) {
    let t = 0, at = REST;
    return style.script.map(([name, d]) => {
      const from = at;
      if (name === "lift" || name === "hold") at = CHEST;
      else if (name === "raise" || name === "test") at = MOUTH;
      else if (name === "lower") at = style.lowerTo || CHEST;
      else if (name === "hot") at = {x: CHEST.x, y: CHEST.y + 1};
      else if (name === "sniff") at = SNUG;
      else if (name === "down") at = REST;
      const o = {name, from: t, to: t + d, start: from, end: at};
      t += d;
      return o;
    });
  }

  // what the break asks for b seconds in: the mug, the paws, the face (null once it is over)
  function breakAt(style, phases, b, now) {
    const ph = phases.find((q) => b >= q.from && b < q.to);
    if (!ph) return null;
    const p = (b - ph.from) / (ph.to - ph.from), e = ease(p);
    const out = {name: ph.name, sc: 1, cup: ph.end, pawL: CHIN, pawR: null, face: {}, wind: 0, puff: 0, q: false};
    if (MOVES.has(ph.name)) {
      out.cup = ph.name === "lift" || ph.name === "down" ? bez(ph.start, CTRL, ph.end, e)
        : lerpP(ph.start, ph.end, ph.name === "hot" ? Math.min(1, p * 4) : e);
    }
    const sway = style.sway ? 0.05 * Math.sin(now / 650) : 0;
    switch (ph.name) {
      case "pop": out.sc = Math.max(0, backOut(p)); out.face = {lookX: 0.9, lookY: 0.8, ears: 0.45, happy: 0.2}; break;
      case "reach": out.pawR = lerpP(PAW_R_REST, add(REST, NEAR), e); out.face = {lookX: 0.9, lookY: 0.8, ears: 0.3, happy: 0.2, tilt: 0.05}; break;
      case "lift": out.pawR = add(out.cup, lerpP(NEAR, UNDER, e));
        out.face = {lookX: Math.max(-1, Math.min(1, (out.cup.x - 21) / 12)), lookY: Math.max(-1, Math.min(1, (out.cup.y - 20) / 10)), happy: 0.25}; break;
      case "hold": out.pawR = add(CHEST, lerpP(UNDER, RIGHT, e)); out.pawL = lerpP(CHIN, add(CHEST, LEFT), e);
        out.face = {lookY: 0.7, happy: 0.4, ears: 0.2}; break;
      case "blow": out.face = {lookY: 0.7, happy: 0.3, mouth: p > 0.15 && p < 0.85 ? 0.35 : 0}; out.wind = Math.sin(Math.PI * p); break;
      case "raise": out.face = {happy: 1, lookY: 0.2}; break;
      case "sip": out.cup = {x: ph.end.x, y: ph.end.y - (p > 0.25 && p < 0.75 ? 1 : 0)}; out.face = {happy: 1, dy: -0.6, tilt: -0.03 + sway}; break;
      case "test": out.face = {lookY: 0.4, dy: -0.3}; break;
      case "hot": out.face = {eye: 1.3, happy: 0, ears: 0.9, dy: -1.1 * (1 - p), mouth: p < 0.6 ? 0.45 : 0,
        tilt: 0.06 * Math.sin(p * 30) * (1 - p)}; out.puff = 1 - p; break;
      case "lower": out.face = {happy: 1, tilt: sway}; break;
      case "ahh": out.face = {happy: 0.95, mouth: p < 0.55 ? 0.6 : 0, wiggle: Math.sin(Math.PI * 2 * p), glow: 1}; break;
      case "cosy": out.face = {happy: 0.7, lookY: 0.5, glow: 0.6, tilt: sway}; break;
      case "sniff": out.face = {happy: 1, ears: -0.25, glow: 0.6, tilt: sway}; break;
      case "sigh": out.face = {happy: 0.9, ears: -0.35, glow: 1, mouth: p > 0.2 && p < 0.7 ? 0.3 : 0, dy: 0.5 * Math.sin(Math.PI * p), tilt: sway}; break;
      case "thinkhold": out.face = null; out.q = true; break;
      case "regrip": out.pawR = add(ph.end, lerpP(RIGHT, UNDER, e)); out.pawL = lerpP(add(ph.end, LEFT), CHIN, e); out.face = null; break;
      case "down": out.pawR = add(out.cup, lerpP(UNDER, NEAR, e)); out.face = null; break;
      case "release": out.pawR = lerpP(add(REST, NEAR), PAW_R_REST, e); out.face = null; break;
      case "fade": out.sc = 1 - e; out.face = null; break;
    }
    if (HELD.has(ph.name)) { out.pawL = add(out.cup, LEFT); out.pawR = add(out.cup, RIGHT); }
    out.cup = {x: Math.round(out.cup.x - 0.5) + 0.5, y: Math.round(out.cup.y - 0.5) + 0.5, sc: out.sc};
    return out;
  }

  // ---------------------------------------------------------------------------------------------------------------
  // work on a long task.  Each activity: an intro, a core played twice, an outro, then 20 s of plain thinking, again
  // and again while the turn runs.  frame(ph, now) gives the props as maps of whole cells, the paws, the face and the
  // floating things (readings, a light bulb, sparkles)
  const WORK_AFTER = 30000, WORK_TOOLS = 6, WORK_REST = 20;
  const GLYPH = {
    "0": ["111", "101", "101", "101", "111"], "1": ["010", "110", "010", "010", "111"], "2": ["111", "001", "111", "100", "111"],
    "3": ["111", "001", "111", "001", "111"], "7": ["111", "001", "010", "010", "010"], "8": ["111", "101", "111", "101", "111"],
    "9": ["111", "101", "111", "001", "111"], "x": ["000", "101", "010", "101", "000"], "+": ["000", "010", "111", "010", "000"],
    "=": ["000", "111", "000", "111", "000"], ".": ["000", "000", "000", "000", "010"],
  };
  const BULB = ["..r.r..", "r.yyy.r", ".yyhyy.", ".yyyyy.", ".yyyyy.", "..yyy..", "..ggg..", "..ggg.."];
  const clamp01 = (v) => Math.max(0, Math.min(1, v));
  const pop = (ph) => ph.name === "pop" ? Math.min(1.15, Math.max(0, backOut(ph.p))) : ph.name === "fade" ? 1 - ph.e : 1;
  // the dots of a text in writing order, from cell (x, y); cells along segments, in drawing order, no repeats
  function textDots(text, x, y) {
    const out = [];
    [...text].forEach((ch, n) => {
      const gl = GLYPH[ch];
      for (let r = 0; r < 5; r++) for (let c = 0; c < 3; c++) if (gl[r][c] === "1") out.push({x: x + n * 4 + c, y: y + r});
    });
    return out;
  }
  function lineCells(segs) {
    const out = [], seen = new Set();
    for (const [x0, y0, x1, y1] of segs) {
      const n = Math.max(Math.abs(x1 - x0), Math.abs(y1 - y0)) * 2 || 1;
      for (let k = 0; k <= n; k++) {
        const x = Math.round(x0 + (x1 - x0) * k / n), y = Math.round(y0 + (y1 - y0) * k / n);
        if (!seen.has(y * COLS + x)) { seen.add(y * COLS + x); out.push({x, y}); }
      }
    }
    return out;
  }
  const PENCIL_HOLD = {x: 2.3, y: -1.6};
  function pencil(map, tip) {
    const tx = Math.round(tip.x), ty = Math.round(tip.y);
    map.set(ty * COLS + tx, "#334155");
    map.set((ty - 1) * COLS + tx + 1, "#facc15");
    map.set((ty - 2) * COLS + tx + 2, "#eab308");
    map.set((ty - 3) * COLS + tx + 3, "#f9a8d4");
  }
  const blank = () => ({prop: new Map(), front: new Map(), overlay: [], face: null, pawL: null, pawR: null});
  // the hands for a prop held from `grab` to `away`: the left paw at L, the right at R
  function hands(F, ph, L, R) {
    if (ph.name === "grab") { F.pawL = L && lerpP(CHIN, L, ph.e); F.pawR = lerpP(PAW_R_REST, R, ph.e); }
    else if (ph.name === "away") { F.pawL = L && lerpP(L, CHIN, ph.e); F.pawR = lerpP(R, PAW_R_REST, ph.e); }
    else if (ph.name !== "pop" && ph.name !== "fade") { F.pawL = L; F.pawR = R; }
  }
  const nod = (p) => 0.7 * Math.sin(Math.PI * 2 * Math.min(1, p * 1.5)) * (p < 0.66 ? 1 : 0);

  // a blue sheet on his lap: a box with a dimension line, wiped, then a gear with its centre line
  const SHEET = {x0: 12, x1: 30, y0: 28, y1: 38};
  const BOX = lineCells([[15, 31, 21, 31], [21, 31, 21, 37], [21, 37, 15, 37], [15, 37, 15, 31], [15, 31, 18, 29], [18, 29, 24, 29],
    [24, 29, 21, 31], [24, 29, 24, 35], [24, 35, 21, 37], [27, 29, 27, 35], [26, 29, 28, 29], [26, 35, 28, 35]]);
  const GEAR = (() => {
    const out = [], seen = new Set();
    for (let a = -Math.PI / 2; a < Math.PI * 1.5; a += 0.04) {
      const r = 3.4 + (Math.cos(a * 8) > 0.2 ? 1.1 : 0);
      const x = Math.round(20 + r * Math.cos(a)), y = Math.round(33 + r * Math.sin(a) * 0.9);
      if (!seen.has(y * COLS + x)) { seen.add(y * COLS + x); out.push({x, y}); }
    }
    out.push({x: 20, y: 32}, {x: 21, y: 33}, {x: 20, y: 34}, {x: 19, y: 33});                         // the shaft hole
    for (let x = 13; x <= 28; x += 2) if (x < 15 || x > 25) out.push({x, y: 33});                     // the centre line
    return out;
  })();
  const blueprint = {
    intro: [["pop", 0.6], ["grab", 0.5]], outro: [["away", 0.5], ["fade", 0.5]],
    core: [["draw1", 4.5], ["admire1", 1.2], ["clear1", 0.6], ["draw2", 4.2], ["admire2", 1.0], ["clear2", 0.6]],
    frame(ph) {
      const F = blank(), sc = pop(ph), cx = (SHEET.x0 + SHEET.x1) / 2, cy = (SHEET.y0 + SHEET.y1) / 2;
      for (let j = SHEET.y0; j <= SHEET.y1; j++) for (let i = SHEET.x0; i <= SHEET.x1; i++) {
        if (Math.abs(i - cx) > (SHEET.x1 - cx) * sc + 0.01 || Math.abs(j - cy) > (SHEET.y1 - cy) * sc + 0.01) continue;
        const edge = i === SHEET.x0 || i === SHEET.x1 || j === SHEET.y0 || j === SHEET.y1;
        F.prop.set(j * COLS + i, edge ? "#0b4a75" : (i % 3 === 0 && j % 3 === 0) ? "#2b7fb8" : "#16629a");
      }
      const gear = /2$/.test(ph.name), path = gear ? GEAR : BOX;
      const n = /^draw/.test(ph.name) ? Math.floor(path.length * ph.p) : /^clear/.test(ph.name) ? Math.floor(path.length * (1 - ph.e))
        : /^admire/.test(ph.name) ? path.length : 0;
      for (let k = 0; k < n; k++) F.prop.set(path[k].y * COLS + path[k].x, "#e0f2fe");
      const drawing = /^draw/.test(ph.name), tip = drawing ? path[Math.max(0, n - 1)] : {x: 24, y: 27};
      hands(F, ph, {x: 12.6, y: 33}, add(tip, PENCIL_HOLD));
      if (F.pawR && ph.name !== "away") pencil(F.front, tip);
      if (drawing) F.face = {lookX: Math.max(-1, Math.min(1, (tip.x - 21) / 9)), lookY: 0.95, tongue: 1, happy: 0.1};
      else if (/^admire/.test(ph.name)) F.face = {happy: 0.75, glow: 0.8, dy: nod(ph.p), ears: 0.3};
      else if (ph.name !== "away" && ph.name !== "fade") F.face = {lookY: 0.9, ears: 0.3};
      return F;
    },
  };

  // a blue printed cube on the input box; calipers slide in, he closes the jaw on it, squints, reads 20.0, then 19.9: hmm?
  const PART = {x0: 35, x1: 40, y0: 34, y1: 39};
  const measure = {
    intro: [["pop", 0.7], ["grab", 0.5]], outro: [["away", 0.5], ["fade", 0.6]],
    core: [["open1", 0.6], ["close1", 1.1], ["squint", 0.8], ["read1", 1.4], ["open2", 0.5], ["close2", 0.8], ["read2", 1.2], ["hmm", 1.0]],
    frame(ph) {
      const F = blank(), sc = pop(ph), pcx = (PART.x0 + PART.x1) / 2;
      for (let j = PART.y0; j <= PART.y1; j++) for (let i = PART.x0; i <= PART.x1; i++) {
        if (Math.abs(i - pcx) > 3 * sc || PART.y1 - j > 6 * sc - 0.5) continue;
        F.prop.set(j * COLS + i, j === PART.y0 ? "#7dd3fc" : i === PART.x1 ? "#0369a1" : (j % 2 ? "#38bdf8" : "#0ea5e9"));
      }
      // calipers: a beam on row 30, a fixed jaw at 41 and a sliding one; they slide in from the right edge and out again
      const open = ph.name === "open1" ? 30 : 31;
      const jx = Math.round(/^open/.test(ph.name) ? lerp(34, open, ph.e) : /^close/.test(ph.name) ? lerp(open, 34, ph.e) : 34);
      const slide = ph.name === "pop" ? Math.round((1 - ph.e) * 14) : ph.name === "fade" ? Math.round(ph.e * 14) : 0;
      const set = (i, j, col) => { if (i + slide < COLS) F.front.set(j * COLS + i + slide, col); };
      for (let i = jx; i <= 44; i++) { set(i, 30, "#e2e8f0"); if (i % 2 === 0 && i > jx + 2) set(i, 29, "#94a3b8"); }
      for (let j = 31; j <= 37; j++) { set(41, j, "#cbd5e1"); set(jx, j, "#cbd5e1"); }
      for (let i = jx; i <= jx + 2; i++) set(i, 29, "#64748b");
      hands(F, ph, null, {x: jx + 1.2, y: 28.2});
      // the reading in the display blue, blinking as it comes up
      const reading = ph.name === "read1" ? "20.0" : ph.name === "read2" || ph.name === "hmm" ? "19.9" : null;
      if (reading && !(/^read/.test(ph.name) && ph.p < 0.3 && Math.floor(ph.p * 13) % 2)) {
        for (const d of textDots(reading, 30, 22)) F.overlay.push({x: d.x, y: d.y, rgb: [56, 189, 248], a: 0.95});
      }
      if (ph.name === "hmm") {
        const a = Math.sin(Math.PI * ph.p), oy = Math.round(4 - ph.p * 2);
        for (let r = 0; r < 7; r++) for (let k = 0; k < 5; k++) if (QMARK[r][k] === "1") F.overlay.push({x: 39 + k, y: oy + r, rgb: [56, 189, 248], a});
      }
      if (ph.name === "pop" || ph.name === "grab" || /^open/.test(ph.name)) F.face = {lookX: 0.9, lookY: 0.9, ears: ph.name === "pop" ? 0.4 : 0.15};
      else if (/^close/.test(ph.name)) F.face = {lookX: 0.9, lookY: 0.9, tongue: 1};
      else if (ph.name === "squint") F.face = {lookX: 0.9, lookY: 0.9, happy: 0.45, eye: 0.85, tongue: 1};
      else if (ph.name === "read1") F.face = {lookX: 0.8, lookY: 0.4, happy: ph.p > 0.4 ? 0.7 : 0.2, glow: 0.6, dy: ph.p > 0.4 ? 0.6 * Math.sin(Math.PI * 2 * (ph.p - 0.4) / 0.6) : 0};
      else if (ph.name === "read2") F.face = {lookX: 0.8, lookY: 0.4, eye: 1.1};
      else if (ph.name === "hmm") F.face = {lookX: 0.5, lookY: -0.3, tilt: 0.09, mouth: 0.25, ears: 0.3};
      return F;
    },
  };

  // a Rubik's cube at his chest: rows and columns turn until the front face is all blue, a hop and sparkles, a scramble
  const CUBE_COLS = ["#ef4444", "#fb923c", "#facc15", "#22c55e", "#38bdf8", "#f6efe4"];
  const CUBE = (() => {
    let seed = 7;
    const rnd = () => (seed = (seed * 9301 + 49297) % 233280) / 233280, pick = () => Math.floor(rnd() * 6);
    const states = [[[0, 3, 4], [5, 4, 1], [2, 4, 0]]], moves = [];
    for (let m = 0; m < 4; m++) {
      const f = states[states.length - 1].map((r) => r.slice()), col = m % 2 === 1, k = Math.floor(rnd() * 3);
      for (let n = 0; n < 3; n++) { if (col) f[n][k] = pick(); else f[k][n] = pick(); }
      moves.push({col, k, dir: rnd() < 0.5 ? -1 : 1}); states.push(f);
    }
    for (let k = 0; k < 3; k++) {
      const f = states[states.length - 1].map((r) => r.slice());
      for (let n = 0; n < 3; n++) f[k][n] = 4;
      moves.push({col: false, k, dir: k % 2 ? 1 : -1}); states.push(f);
    }
    return {states, moves, gaps: [0.5, 0.3, 0.7, 0.35, 0.45, 0.3, 0.25], turn: 0.34};
  })();
  const cube = {
    intro: [["pop", 0.5], ["grab", 0.4]], outro: [["away", 0.5], ["fade", 0.5]],
    core: [["turns", CUBE.moves.length * CUBE.turn + CUBE.gaps.reduce((a, b) => a + b, 0)], ["solved", 1.8], ["scramble", 0.6]],
    frame(ph) {
      const F = blank(), sc = pop(ph);
      let state = CUBE.states[0], move = null, q = 0, lookX = 0;
      if (ph.name === "turns") {
        let t = ph.p * this.core[0][1], n = 0;
        for (; n < CUBE.moves.length; n++) {
          if (t < CUBE.turn) { move = CUBE.moves[n]; q = t / CUBE.turn; break; }
          t -= CUBE.turn;
          if (t < CUBE.gaps[n]) break;
          t -= CUBE.gaps[n];
        }
        state = CUBE.states[Math.min(n + (move && q >= 0.5 ? 1 : 0), CUBE.states.length - 1)];
        const m = CUBE.moves[Math.min(n, CUBE.moves.length - 1)];
        lookX = m.col ? (m.k - 1) * 0.5 : 0;
      } else if (ph.name === "solved" || (ph.name === "scramble" && ph.p < 0.5)) state = CUBE.states[CUBE.states.length - 1];
      const lift = ph.name === "solved" ? Math.round(-2 * Math.sin(Math.PI * Math.min(1, ph.p * 1.4))) : 0;
      const shake = ph.name === "scramble" ? (Math.floor(ph.p * 8) % 2 ? 1 : -1) : 0;
      const ox = 17 + shake, oy = 26 + lift, half = 4.5;
      for (let j = 0; j < 10; j++) for (let i = 0; i < 10; i++) {
        if (Math.abs(i - half) > (half + 0.5) * sc || Math.abs(j - half) > (half + 0.5) * sc) continue;
        let col = "#111827";
        const si = i - 1, sj = j - 1;
        if (i > 0 && i < 9 && j > 0 && j < 9 && si % 3 !== 2 && sj % 3 !== 2) {
          let r = Math.floor(sj / 3), c = Math.floor(si / 3), gap = false;
          // the turning row or column is shown one dot along its way for the first half of the move
          if (move && q < 0.5) {
            if (!move.col && r === move.k) { const v = si - move.dir; gap = v < 0 || v > 7 || v % 3 === 2; c = Math.floor(v / 3); }
            if (move.col && c === move.k) { const v = sj - move.dir; gap = v < 0 || v > 7 || v % 3 === 2; r = Math.floor(v / 3); }
          }
          if (!gap) col = CUBE_COLS[state[r][c]];
        }
        F.prop.set((oy + j) * COLS + ox + i, col);
      }
      hands(F, ph, {x: 16.2 + shake, y: 31 + lift}, {x: 27.6 + shake, y: 31 + lift});
      if (ph.name === "solved") {
        for (const [x, y, p0] of [[14, 24, 0], [30, 25, 0.3], [12, 31, 0.55], [32, 31, 0.8]]) {
          const a = Math.max(0, Math.sin(Math.PI * 2 * (ph.p * 2 + p0)));
          if (a > 0.2) for (const [dx, dy] of [[0, 0], [1, 0], [-1, 0], [0, 1], [0, -1]]) {
            F.overlay.push({x: x + dx, y: y + dy + lift, rgb: dx || dy ? [250, 204, 21] : [255, 255, 255], a});
          }
        }
      }
      if (ph.name === "pop" || ph.name === "grab" || ph.name === "scramble") F.face = {lookY: 0.8, ears: 0.3};
      else if (ph.name === "turns") F.face = {lookX, lookY: 0.8, tongue: 1, ears: move ? 0.35 : 0.15};
      else if (ph.name === "solved") F.face = {happy: ph.p < 0.25 ? 0 : 0.8, eye: ph.p < 0.25 ? 1.25 : 1, ears: 0.8, glow: 1,
        dy: -1.2 * Math.sin(Math.PI * Math.min(1, ph.p * 2.5)), mouth: ph.p < 0.3 ? 0.5 : 0};
      return F;
    },
  };

  // a notepad on his lap: 2x+1 = 7, the pencil tapping his chin, a light bulb, a fresh page: x=3, underlined
  const PAD = {x0: 13, x1: 29, y0: 26, y1: 39};
  const LINE1 = textDots("2x+1", 14, 28), LINE2 = textDots("=7", 14, 34), ANSWER = textDots("x=3", 15, 29);
  const UNDERLINE = lineCells([[15, 35, 25, 35]]);
  const maths = {
    intro: [["pop", 0.5], ["grab", 0.5]], outro: [["away", 0.5], ["fade", 0.5]],
    core: [["write1", 2.4], ["write2", 1.2], ["ponder", 1.6], ["aha", 1.1], ["flip1", 0.5], ["write3", 1.8], ["underline", 0.5],
      ["proud", 1.1], ["flip2", 0.5]],
    frame(ph) {
      const F = blank(), sc = pop(ph), cx = (PAD.x0 + PAD.x1) / 2, ink = "#1e3a8a";
      for (let j = PAD.y0; j <= PAD.y1; j++) for (let i = PAD.x0; i <= PAD.x1; i++) {
        if (Math.abs(i - cx) > (PAD.x1 - cx) * sc + 0.01 || PAD.y1 - j > (PAD.y1 - PAD.y0) * sc + 0.01) continue;
        F.prop.set(j * COLS + i, j === PAD.y0 ? (i % 2 ? "#64748b" : "#cbd5e1") : i === PAD.x1 ? "#e2d6c6" : "#fbf7f0");
      }
      const page1 = ["write1", "write2", "ponder", "aha", "flip1"].includes(ph.name);
      const page2 = ["write3", "underline", "proud", "flip2"].includes(ph.name);
      // a page turn: the writing disappears from the top down
      const cut = /^flip/.test(ph.name) ? PAD.y0 + 1 + ph.e * 13 : 0;
      const ink1 = (dots, n, col = ink) => { for (let k = 0; k < n; k++) if (dots[k].y >= cut) F.prop.set(dots[k].y * COLS + dots[k].x, col); };
      let tip = null;
      if (page1) {
        const n1 = ph.name === "write1" ? Math.floor(LINE1.length * ph.p) : LINE1.length;
        const n2 = ph.name === "write1" ? 0 : ph.name === "write2" ? Math.floor(LINE2.length * ph.p) : LINE2.length;
        ink1(LINE1, n1); ink1(LINE2, n2);
        if (ph.name === "write1") tip = LINE1[Math.max(0, n1 - 1)];
        if (ph.name === "write2") tip = LINE2[Math.max(0, n2 - 1)];
      }
      if (page2) {
        const n3 = ph.name === "write3" ? Math.floor(ANSWER.length * ph.p) : ANSWER.length;
        const nu = ph.name === "write3" ? 0 : ph.name === "underline" ? Math.floor(UNDERLINE.length * ph.e) : UNDERLINE.length;
        ink1(ANSWER, n3); ink1(UNDERLINE, nu, "#2563eb");
        if (ph.name === "write3") tip = ANSWER[Math.max(0, n3 - 1)];
        if (ph.name === "underline") tip = UNDERLINE[Math.max(0, nu - 1)];
      }
      // the pencil: on the paper while writing, tapping his chin while he ponders, hovering otherwise
      const pTip = tip || (ph.name === "ponder" ? {x: 24.5, y: 21.5 + (Math.floor(ph.p * 8) % 2)} : {x: 24, y: 25});
      hands(F, ph, {x: 13.2, y: 32}, add(pTip, PENCIL_HOLD));
      if (F.pawR && ph.name !== "away") pencil(F.front, pTip);
      if (ph.name === "aha" || ph.name === "flip1") {
        const a = ph.name === "aha" ? Math.min(1, ph.p * 3) : 1 - ph.p;
        BULB.forEach((row, r) => [...row].forEach((ch, k) => {
          const rgb = {y: [250, 204, 21], h: [255, 255, 255], g: [148, 163, 184], r: [253, 224, 71]}[ch];
          if (rgb && (ch !== "r" || Math.floor(ph.p * 6) % 2 === 0)) F.overlay.push({x: 37 + k, y: 1 + r, rgb, a});
        }));
      }
      if (ph.name === "pop" || ph.name === "grab") F.face = {lookY: 0.9, ears: 0.3};
      else if (tip) F.face = {lookX: Math.max(-1, Math.min(1, (tip.x - 21) / 9)), lookY: 0.95, tongue: 1};
      else if (ph.name === "ponder") F.face = {lookX: 0.7, lookY: -0.75, tilt: -0.05, ears: 0.15};
      else if (ph.name === "aha") F.face = {eye: 1.25, ears: 0.9, mouth: ph.p < 0.5 ? 0.5 : 0, lookX: 0.6, lookY: -0.6, dy: -0.8 * Math.sin(Math.PI * Math.min(1, ph.p * 2))};
      else if (/^flip/.test(ph.name)) F.face = {lookY: 0.9, happy: 0.3};
      else if (ph.name === "proud") F.face = {happy: 0.8, glow: 1, dy: nod(ph.p), ears: 0.3};
      return F;
    },
  };
  const WORKS = {blueprint, measure, cube, maths};
  // which activities fit which work, with weights: the first is the usual one, the others come up some of the time.
  // "hard" is many failed tool calls; "long" is a long think with no kind of work recognised (only 1 round in 3)
  const POOLS = {
    code: {blueprint: 3, maths: 1, cube: 1},
    model: {blueprint: 3, measure: 1},
    print: {measure: 3, blueprint: 1},
    maths: {maths: 3, cube: 1},
    hard: {cube: 3},
    long: {cube: 1},
  };
  const MAIN = {code: "blueprint", model: "blueprint", print: "measure", maths: "maths"};

  // what kind of work a turn is, from its prompt and tool calls; the newest signal wins, many failures make it a puzzle
  const RE_PRINT = /\b(3d[- ]?print\w*|printer|printing|bambu|prusa|octoprint|klipper|moonraker|g-?code|filament|slicer|nozzle)\b|\.(gcode|3mf)\b/i;
  const RE_MODEL = /\b(solidcraft|cad|3d model\w*|mesh|openscad|build123d|cadquery|fillet|extrude|stl)\b|\.(stl|step|stp|scad|obj)\b/i;
  const RE_MATHS = /\b(math\w*|equations?|integral|derivative|algebra|calculus|matri(x|ces)|proof|solve for|probability|statistics?)\b|\d\s*[+*\/^=]\s*\d/i;
  const RE_CODE_TOOL = /^(write_to_file|replace_file_content|multi_replace\w*|create_file|edit_file|run_command)$/;
  const RE_CODE_FILE = /\.(py|js|mjs|ts|tsx|jsx|rs|go|c|cc|cpp|h|hpp|java|kt|swift|rb|php|cs|sh|html|css|cu|hip|json|toml|yaml|yml)\b/i;
  function kindOf(text, toolName) {
    text = text.replace(/_+/g, " ");                                 // tool names like bambu__print_status
    if (RE_PRINT.test(text)) return "print";
    if (RE_MODEL.test(text)) return "model";
    if (RE_MATHS.test(text)) return "maths";
    if (toolName != null && (RE_CODE_TOOL.test(toolName) || RE_CODE_FILE.test(text))) return "code";
    return null;
  }
  const task = {at: 0, tools: 0, errors: 0, kind: null};
  let lastWork = "", lastWorkRuns = 0, workRestUntil = 0;

  // the next round's activity: a weighted pick from what fits, never the same one three times running
  function pickWork() {
    const k = task.errors >= 3 ? "hard" : task.kind || "long";
    if (k === "long" && Math.random() >= 1 / 3) return null;
    const pool = {...POOLS[k]};
    if (k === "hard" && MAIN[task.kind]) pool[MAIN[task.kind]] = 1;
    if (lastWorkRuns >= 2 && Object.keys(pool).length > 1) delete pool[lastWork];
    const names = Object.keys(pool), sum = names.reduce((t, n) => t + pool[n], 0);
    let r = Math.random() * sum;
    const name = names.find((n) => (r -= pool[n]) < 0) || names[names.length - 1];
    lastWorkRuns = name === lastWork ? lastWorkRuns + 1 : 1;
    lastWork = name;
    return name;
  }

  // the phase of a round at time b (intro, the core twice, outro), or null once the round is over
  function workPhase(W, b) {
    const len = (list) => list.reduce((t, [, d]) => t + d, 0);
    const I = len(W.intro), K = len(W.core);
    let t = b, list = W.intro;
    if (t >= I && t < I + 2 * K) { t = (t - I) % K; list = W.core; }
    else if (t >= I + 2 * K) { t -= I + 2 * K; list = W.outro; }
    for (const [name, d] of list) {
      if (t < d) return {name, p: t / d, e: ease(t / d)};
      t -= d;
    }
    return null;
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
  let level = 0, paused = false, mode = "idle";   // "think" | "audio" | "text" | "warm" | "leave" | "idle"
  let analyser = null, tbuf = null;
  let line = null;                            // the chunk being spoken: {text, times[], amp[], sentences[], total, …}
  let audioText = null, audioStart = 0, audioDur = 0, audioCtx = null;
  let speed = 1, thinkAt = 0;
  // the cocoa break: when it may start in this think, the one playing, the mug being taken away, and what came before
  let breakDue = Infinity, brk = null, mugOut = null, lastHadBreak = false, lastStyle = "", sip = null;
  // work on a long task: the activity running ({name, t0}) and this frame's props
  let work = null, wf = null;
  const calmMotion = () => !!(window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches);
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
    let tgt = think ? {...target, lookX: 0.7 + 0.25 * Math.sin(t / 2.4), lookY: -0.75, tilt: -0.06 + 0.03 * Math.sin(t / 3.1)} : target;
    // a cocoa break, once its time has come in this think
    // a long task: a round of work (instead of a cocoa break), then 20 s of plain thinking, then the next pick
    const due = think && !calmMotion() && task.at > 0 && (now - task.at >= WORK_AFTER || task.tools >= WORK_TOOLS);
    if (!think) work = null;
    else if (due && !brk && !work && now >= workRestUntil) {
      const name = pickWork();
      if (name) work = {name, t0: now};
      else workRestUntil = now + WORK_REST * 1000;                   // not this time: a cocoa break may come instead
    }
    let wp = work && workPhase(WORKS[work.name], (now - work.t0) / 1000);
    if (work && !wp) { work = null; workRestUntil = now + WORK_REST * 1000; }
    wf = wp ? WORKS[work.name].frame(wp, now) : null;
    if (think && !brk && !work && now >= breakDue) startBreak(now);
    sip = brk ? breakAt(STYLES[brk.style], brk.phases, (now - brk.t0) / 1000, now) : null;
    if (brk && !sip) brk = null;
    if (sip) {
      pose.cup = sip.cup; pose.pawL = sip.pawL; pose.pawR = sip.pawR;
      if (sip.face) tgt = {...calm("neutral"), lookX: 0, lookY: 0, tilt: 0, ears: 0.15, ...sip.face};
    } else if (mugOut) {
      const k = 1 - (now - mugOut.t0) / 250;                         // taken away: the mug shrinks, the arms are his own
      pose.cup = k > 0 ? {...mugOut.cup, sc: mugOut.cup.sc * k} : null;
      pose.pawL = pose.pawR = null;
      if (k <= 0) mugOut = null;
    } else {
      pose.cup = null;
      pose.pawL = wf ? wf.pawL : null;
      pose.pawR = wf ? wf.pawR : null;
      if (wf && wf.face) tgt = {...calm("neutral"), lookX: 0, lookY: 0, tilt: 0, ears: 0.15, ...wf.face};
    }
    pose.work = wf;
    const f = (sip && sip.face) || (wf && wf.face) || {};
    pose.tongue = f.tongue || 0;
    spring(pose, "paw", think ? 1 : 0, 0.08, 0.75);

    // squash and stretch (volume kept), the nod, the settle
    spring(pose, "sy", 1 - 0.035 * level, 0.25, 0.62);
    pose.sx = 1 / pose.sy;
    spring(pose, "dy", 0.7 * stressK + 0.55 * settleK + (f.dy || 0), 0.14, 0.74);
    // mood, eased slowly; ears and tail follow a beat later, with an extra flick on stresses
    for (const k of ["eye", "happy", "tilt"]) spring(pose, k, (tgt[k] ?? EXPR.neutral[k]) + (k === "happy" && talking ? 0.25 * stressK : 0), 0.05, 0.8);
    if (f.eye) spring(pose, "eye", f.eye, 0.2, 0.65);                  // a startled jolt is quick
    spring(pose, "glow", f.glow || 0, 0.05, 0.8);
    spring(pose, "rot", pose.tilt, 0.06, 0.8);
    spring(pose, "ears", tgt.ears, 0.04, 0.82);
    const wig = f.wiggle || 0;                                         // the ears take turns after an "ahh"
    spring(pose, "earL", 0.18 * stressK + (mem.twitchSide < 0 ? 0.5 * twitch : 0) + 0.5 * Math.max(0, wig), 0.18, 0.68);
    spring(pose, "earR", 0.25 * stressK + (think ? 0.2 : 0) + (mem.twitchSide > 0 ? 0.5 * twitch : 0) + 0.5 * Math.max(0, -wig), 0.18, 0.68);
    spring(pose, "tail", 0.1 * Math.sin(now / 1600) - 0.12 * Math.exp(-(now - mem.stressAt - 120) / 300) * (now > mem.stressAt + 120 ? 1 : 0), 0.05, 0.85);
    spring(pose, "lookX", tgt.lookX + mem.glance.x, 0.08, 0.8);
    spring(pose, "lookY", tgt.lookY + mem.glance.y, 0.08, 0.8);
    // the mouth: only an accent on the strongest syllables
    spring(pose, "mouth", talking && level > 0.8 ? 0.4 + 0.6 * stressK : f.mouth || 0, 0.3, 0.6);
  }

  // the page colour behind him (read again now and then, so a theme switch follows).  The gaps between his dots take a
  // darker shade of each dot's own colour and the dots are large, so he stays solid and saturated instead of washed out
  // by white gaps or sunk into dark ones; on a light page a thin dark line follows his edge, on a dark page nothing
  let bgAt = 0, lightPage = false;
  const shadeCache = {};
  function deeper(hex) {
    if (!shadeCache[hex]) {
      const n = parseInt(hex.slice(1), 16), f = 0.8;
      shadeCache[hex] = `rgb(${((n >> 16) & 255) * f | 0},${((n >> 8) & 255) * f | 0},${(n & 255) * f | 0})`;
    }
    return shadeCache[hex];
  }
  // the floating dots, with no backing: steam from the mug (two wisps of dashes rising from the rim, swaying and fading
  // with height; a puff when it is too hot, bent away when he blows on it) and the work's readings, light bulb and
  // sparkles.  On a light page white turns warm grey or amber, which would otherwise vanish
  function floaters(now, light) {
    const out = [];
    if (pose.cup && pose.cup.sc > 0.3) {
      const ts = now / 1000, top = pose.cup.y - 5 * pose.cup.sc;
      const heat = Math.min(1, (pose.cup.sc - 0.3) / 0.7) * (1 + 0.6 * (sip ? sip.puff : 0)), wind = sip ? sip.wind : 0;
      const rgb = light ? [150, 130, 115] : [246, 239, 228];
      for (let w = 0; w < 2; w++) {
        for (let h = 0; h < 9; h++) {
          const gap = (h + ts * 3.2 + w * 1.7) % 3.4;
          if (gap > 2.1) continue;
          const x = Math.floor(pose.cup.x + (w ? 1 : -1) + Math.sin(h * 0.8 - ts * 2.6 + w * 2) * (0.5 + h * 0.08) + wind * h * 0.9);
          out.push({x, y: Math.floor(top - h), rgb, a: Math.min(0.9, heat * 0.62) * (1 - h / 9) * (gap < 0.4 ? gap / 0.4 : 1)});
        }
      }
    }
    if (wf) {
      for (const o of wf.overlay) out.push({...o, rgb: light && o.rgb[0] > 240 && o.rgb[1] > 240 ? [180, 140, 20] : o.rgb});
    }
    return out.filter((o) => o.a >= 0.05 && o.x >= 0 && o.x < COLS && o.y >= 0 && o.y < ROWS);
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
    const P = geo.pitch, rad = P * 0.47;
    for (let j = 0; j < ROWS; j++) for (let i = 0; i < COLS; i++) cells[j * COLS + i] = pandaCell(i + 0.5, j + 0.5, pose);
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
    // on a light page, a thin dark line along his outer edge, so his whites keep an edge without a heavy outline
    if (lightPage) {
      const lit = (i, j) => i >= 0 && i < COLS && j >= 0 && j < ROWS && !!cells[j * COLS + i];
      g.strokeStyle = C.edge;
      g.lineWidth = Math.max(1.5, P * 0.32);
      g.lineCap = "square";
      g.beginPath();
      for (let j = 0; j < ROWS; j++) {
        for (let i = 0; i < COLS; i++) {
          if (!lit(i, j)) continue;
          const x0 = geo.offX + i * P, y0 = geo.offY + j * P;
          if (!lit(i, j - 1)) { g.moveTo(x0, y0); g.lineTo(x0 + P, y0); }
          if (!lit(i, j + 1)) { g.moveTo(x0, y0 + P); g.lineTo(x0 + P, y0 + P); }
          if (!lit(i - 1, j)) { g.moveTo(x0, y0); g.lineTo(x0, y0 + P); }
          if (!lit(i + 1, j)) { g.moveTo(x0 + P, y0); g.lineTo(x0 + P, y0 + P); }
        }
      }
      g.stroke();
    }
    for (const o of floaters(now, lightPage)) {
      g.fillStyle = `rgba(${o.rgb[0]},${o.rgb[1]},${o.rgb[2]},${o.a.toFixed(3)})`;
      g.beginPath();
      g.arc(geo.offX + (o.x + 0.5) * P, geo.offY + (o.y + 0.5) * P, rad * 0.88, 0, Math.PI * 2);
      g.fill();
    }
    // while thinking, a question mark every 2.6 s rises beside his head and fades (no outline, no backing)
    const thinkingNow = pose.paw > 0.5 && (sip ? sip.q : !mugOut) && !wf;
    const qt = ((now - thinkAt) / 1000 % 2.6) / 2.6, qa = thinkingNow ? Math.sin(Math.PI * qt) : 0, qy = 3 - qt * 2;
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

  // the model is working (every prompt, or only spoken ones with "Show Ray thinking on every prompt" off): he appears
  // in his thinking pose until he speaks (or the turn ends)
  function thinking() {
    if (mode === "audio" || mode === "text") return;   // already speaking
    if (mode === "think" && visible) return;           // already thinking: keep his pose going
    show();
    mode = "think";
    thinkAt = performance.now();
    target = calm("neutral");
    // a cocoa break 8 s into this think, by chance, never on two thinks in a row, and not with reduced motion
    breakDue = !lastHadBreak && !calmMotion() && Math.random() < BREAK_CHANCE ? thinkAt + BREAK_AFTER : Infinity;
    lastHadBreak = false;
  }

  // a cocoa break starts now, in a style other than the last one (or the one asked for)
  function startBreak(now, style) {
    const names = Object.keys(STYLES).filter((n) => n !== lastStyle);
    style = STYLES[style] ? style : names[Math.floor(Math.random() * names.length)];
    brk = {style, t0: now, phases: phasesOf(STYLES[style])};
    lastStyle = style; lastHadBreak = true; breakDue = Infinity;
  }

  // the break stops early (he speaks, the answer arrives, the turn ends): the mug is taken away quickly
  function dropBreak() {
    breakDue = Infinity;
    work = null; wf = null;
    if (brk && sip) mugOut = {cup: sip.cup, t0: performance.now()};
    brk = null; sip = null;
  }

  // a chunk of server audio starts playing through `an`; `text` and `duration` give the sentence moods their timing
  function speakAudio(an, text, ctx, startAt, duration) {
    dropBreak();
    show();
    analyser = an;
    audioText = plan(text || "");
    audioCtx = ctx; audioStart = startAt; audioDur = duration;
    mode = "audio";
    paused = false;
  }

  // a chunk starts with the browser's voice
  function speakText(text, rate = 1) {
    dropBreak();
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
    if (!visible || !el || mode === "leave") return;
    dropBreak();
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

  // the answer of a typed prompt starts: he stops thinking and fades out at once, without the goodbye
  function leave() {
    if (!visible || !el || mode !== "think") return;
    dropBreak();
    mode = "leave";
    target = calm("neutral");
    clearTimeout(warmTimer); clearTimeout(hideTimer);
    el.classList.remove("is-on");
    hideTimer = setTimeout(() => {
      el.hidden = true;
      visible = false;
      mode = "idle";
      makeRoom(false);
    }, FADE_OUT);
  }

  window.addEventListener("resize", () => { if (visible) { place(); layout(); } });
  // start a cocoa break now while he is thinking (for trying it out): cocoa("classic" | "savour" | "hot" | "thinking")
  // what the Code tab tells him about the turn: a new prompt, each tool call, a failed tool call
  function taskStart(prompt) {
    Object.assign(task, {at: performance.now(), tools: 0, errors: 0, kind: kindOf(String(prompt || ""), null)});
    workRestUntil = 0;
  }
  function taskTool(name, args) {
    task.tools++;
    let text = String(name || "");
    try { text += " " + JSON.stringify(args || {}).slice(0, 400); } catch (e) { /* args that do not serialise */ }
    task.kind = kindOf(text, String(name || "")) || task.kind;
  }
  function taskError() { task.errors++; }

  // start an activity now while he is thinking (for trying it out): work("blueprint" | "measure" | "cube" | "maths")
  function startWork(name) {
    if (mode !== "think" || !WORKS[name]) return false;
    brk = null; sip = null;
    task.at = performance.now() - WORK_AFTER;
    work = {name, t0: performance.now()};
    return true;
  }

  function cocoa(style) {
    if (mode !== "think" || brk) return false;
    startBreak(performance.now(), style);
    return true;
  }

  return {thinking, speakAudio, speakText, boundary, chunkEnd, pause, end, leave, moodOf, cocoa, taskStart, taskTool, taskError,
          work: startWork,
          get visible() { return visible; },
          get state() { return {...pose, mode, level, mood, cocoa: brk && brk.style, phase: sip && sip.name,
            work: work && work.name, task: {...task}}; },
          set onStop(fn) { onStop = fn; }};
})();
