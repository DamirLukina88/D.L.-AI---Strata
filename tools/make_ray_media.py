"""make_ray_media.py - pictures and animations of Ray, the red panda, for the README and the GitHub page.

    python3 tools/make_ray_media.py

Runs serve/web/rayface.js itself in node (its own drawing, springs and timing, with a fixed random seed), so the
pictures show what the web app shows.  Writes into docs/media/ray/:

    ray.png                 Ray sitting, neutral (the README's header)
    mood-<name>.png         each mood the sentence rules pick, settled at the strength the app uses
    moods.png               all moods on one sheet, labelled
    thinking.gif            the thinking pose: paw on his chin, question marks rising
    talking.gif             reading a reply aloud, moved by the loudness of real Piper speech (needs Piper)
    goodbye.gif             the warm goodbye and the fade
    cocoa-<style>.gif       a cocoa break while thinking, in each of its four styles
    work-<activity>.gif     work on a long task: one round of each activity (its core once)
    home-<panel>.gif        a Home Assistant control panel: one round of each
    social.png              1280 x 640 social preview for the repository page

Needs node and Pillow; talking.gif also needs Piper (serve/speech.py).  Run it again after changing how Ray looks.
"""
from __future__ import annotations

import io
import json
import struct
import subprocess
import sys
import wave
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "serve" / "web"
OUT = ROOT / "docs" / "media" / "ray"
SURFACE = (18, 22, 27)            # --st-surface of the dark theme
TEXT = (230, 234, 238)
MUTED = (140, 150, 160)
RIM = (56, 189, 248)              # the question marks' blue
FPS = 15
MOODS = ["neutral", "happy", "excited", "surprised", "curious", "thinking", "concerned", "warm"]
COCOA = ["classic", "savour", "hot", "thinking"]
WORK = ["blueprint", "measure", "cube", "maths"]
HOME = ["lamp", "mixer", "thermostat"]
LINES = ("Hi, I'm Ray! The build passed and everything works. "
         "Hmm, maybe we should check the printer first? "
         "Sorry, the camera is offline right now.")

# node: load rayface.js with a few internals exposed, drive its own step() at 60 Hz and print one grid per frame
NODE = r"""
const fs = require("fs");
const src = fs.readFileSync(process.argv[1], "utf8");
const job = JSON.parse(fs.readFileSync(0, "utf8"));
let seed = 7;
Math.random = () => (seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648;
const noop = () => {};
global.window = {addEventListener: noop, devicePixelRatio: 1};
global.document = {getElementById: () => null};
global.performance = {now: () => 0};
global.requestAnimationFrame = noop;
const R = new Function(src.replace("return {thinking, speakAudio",
  `return {__x: {pandaCell, qmarkCell, step, pose, newPose, calm, EXPR, floaters, startBreak, WORKS, STYLES,
     set(o) {
       if ("work" in o) work = o.work;
       if ("task" in o) Object.assign(task, o.task);
       if ("mode" in o) mode = o.mode;
       if ("target" in o) target = o.target;
       if ("thinkAt" in o) thinkAt = o.thinkAt;
       if ("audio" in o) { analyser = o.audio.analyser; audioText = plan(o.audio.text); audioCtx = o.audio.ctx;
                           audioStart = 0; audioDur = o.audio.dur; }
       if ("mem" in o) Object.assign(mem, o.mem);
       if ("moodAt" in o) { moodAt = o.moodAt; mood = "neutral"; }
     },
     get mood() { return mood; }},
   thinking, speakAudio`) + "; return RayFace;")();
const X = R.__x;

// the loudness source for "audio" mode: the PCM samples of real speech, read at the fake clock
const ctx = {currentTime: 0};
const pcm = job.pcm || [], sr = job.sr || 22050;
const analyser = {fftSize: 1024, getFloatTimeDomainData(buf) {
  const at = Math.floor(ctx.currentTime * sr);
  for (let i = 0; i < buf.length; i++) { const k = at - buf.length + i; buf[i] = k >= 0 && k < pcm.length ? pcm[k] : 0; }
}};

// one frame: a colour per cell; "q1"/"q0" for the question mark, "f:r,g,b,a" for steam and other floating dots
function grid(qa, qy, t) {
  const rows = [];
  for (let j = 0; j < 40; j++) {
    const r = [];
    for (let i = 0; i < 46; i++) {
      let c = X.pandaCell(i + 0.5, j + 0.5, X.pose);
      if (!c && qa > 0.25 && i >= 34 && X.qmarkCell(i + 0.5, j + 0.5, 39.5, qy)) c = qa > 0.6 ? "q1" : "q0";
      r.push(c || "");
    }
    rows.push(r);
  }
  for (const o of X.floaters(t || 0, false)) rows[o.y][o.x] = `f:${o.rgb.join(",")},${o.a.toFixed(2)}`;
  return rows;
}

const quiet = {blinkAt: -1e9, nextIdleBlink: 1e12, twitchAt: 1e12, stressAt: -1e9, settleAt: -1e9,
               lastLoud: 0, wasTalking: false, glance: {x: 0, y: 0}, glanceNext: {x: 0, y: 0}};
function reset() { Object.assign(X.pose, X.newPose()); for (const k of Object.keys(X.pose)) delete X.pose[k + "_v"]; }

const out = {};
// one still per mood: settled for 4 s at the app's strength (warm, the goodbye, is used in full), eyes open
for (const m of job.moods) {
  reset();
  X.set({mode: "idle", target: m === "warm" ? {...X.EXPR.warm} : X.calm(m), mem: quiet});
  for (let t = 0; t < 4000; t += 1000 / 60) X.step(t);
  out["mood-" + m] = [grid(0, 0)];
}

// a scene: run step() at 60 Hz from 0 to `ms`, keep every fourth frame (15 fps)
function scene(ms, mode, setup, extra, before) {
  reset();
  X.set({mode, target: X.calm("neutral"), thinkAt: 0, moodAt: -1e9, mem: {...quiet, blinkAt: -1e9, nextIdleBlink: 2600, twitchAt: 1800}});
  if (setup) setup();
  const frames = [];
  let n = 0;
  for (let t = 0; t < ms; t += 1000 / 60, n++) {
    ctx.currentTime = t / 1000;
    if (before) before(t);
    X.step(t);
    if (n % 4) continue;
    let qa = 0, qy = 0;
    if (mode === "think" && !X.pose.cup && !X.pose.work) {
      const qt = (t / 1000 % 2.6) / 2.6;
      qa = X.pose.paw > 0.5 ? Math.sin(Math.PI * qt) : 0; qy = 3 - qt * 2;
    }
    frames.push(extra ? [grid(qa, qy, t), extra(t)] : grid(qa, qy, t));
  }
  return frames;
}
out.thinking = scene(5200, "think");
if (pcm.length) out.talking = scene(job.dur * 1000 + 400, "audio", () => X.set({audio: {analyser, text: job.text, ctx, dur: job.dur}}));
// the goodbye: the warm look and a nod for 1.8 s, then a 0.7 s fade (as RayFace.end)
out.goodbye = scene(2900, "warm", () => { X.set({target: {...X.EXPR.warm}, mem: {stressAt: 0}}); },
                    (t) => t < 1800 ? 1 : Math.max(0, 1 - (t - 1800) / 700));
// a cocoa break in each style: a second of thinking, the break, a second of thinking
const len = (list) => list.reduce((a, [, d]) => a + d, 0) * 1000;
for (const style of job.cocoa) {
  let started = false;
  out["cocoa-" + style] = scene(len(X.STYLES[style].script) + 2000, "think", null, null,
    (t) => { if (!started && t >= 1000) { started = true; X.startBreak(t, style); } });
}
// one round of each activity, with its core once: intro and core, then a jump to the outro, then a second of thinking
for (const name of job.work) {
  const W = X.WORKS[name], I = len(W.intro), K = len(W.core), O = len(W.outro);
  let jumped = false;
  out["work-" + name] = scene(I + K + O + 1800, "think", () => X.set({work: {name, t0: 0}, task: {at: 1, tools: 99, kind: "code"}}),
    null, (t) => { if (!jumped && t >= I + K) { jumped = true; X.set({work: {name, t0: -K}}); } });
}
// one round of each Home Assistant panel, as it plays (its core once), then a second of thinking
for (const name of job.home) {
  const W = X.WORKS[name];
  out["home-" + name] = scene(len(W.intro) + len(W.core) + len(W.outro) + 1800, "think",
    () => X.set({work: {name, t0: 0}, task: {at: 0, tools: 0, kind: null}}));
}
process.stdout.write(JSON.stringify(out));
"""


def speech() -> tuple[list[float], int, float] | None:
    """the samples of LINES in Ray's voice, at the web app's default pitch (1.5: asked slower, played faster)"""
    sys.path.insert(0, str(ROOT))
    try:
        from serve import speech as sp
        wav = sp.synthesize(LINES, speed=1 / 1.5)
    except Exception as e:                                     # no Piper here: skip talking.gif
        print(f"no talking.gif: {e}", file=sys.stderr)
        return None
    w = wave.open(io.BytesIO(wav))
    raw = w.readframes(w.getnframes())
    n = len(raw) // 2
    pcm = [v / 32768 for v in struct.unpack(f"<{n}h", raw[:2 * n])]
    sr = int(w.getframerate() * 1.5)                           # played 1.5x faster
    step = 2                                                    # half the samples are plenty for a loudness
    return pcm[::step], sr // step, n / sr


def run_node(job: dict) -> dict:
    r = subprocess.run(["node", "-e", NODE, str(WEB / "rayface.js")], input=json.dumps(job),
                       capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


def rgb(c: str) -> tuple[int, int, int]:
    return int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)


def colour(c: str) -> tuple[int, int, int]:
    if c.startswith("f:"):                                      # a floating dot, see-through, over the surface
        *v, a = (float(x) for x in c[2:].split(","))
        return tuple(int(s + (r - s) * a) for s, r in zip(SURFACE, v))
    if c == "q1":
        return (246, 239, 228)
    if c == "q0":                                               # rgba(56,189,248,0.45) over the surface
        return tuple(int(s + (r - s) * 0.45) for s, r in zip(SURFACE, RIM))
    return rgb(c)


def mix(c, a):
    return tuple(int(s + (v - s) * a) for s, v in zip(SURFACE, c))


def tile(grid, cell: int, pad: int = 2, alpha: float = 1.0, radius: float = 0.12, scale: int = 3) -> Image.Image:
    """the panda as the web app draws it (a darker backing, a large round dot) on a rounded dark tile"""
    cols, rows = len(grid[0]) + 2 * pad, len(grid) + 2 * pad
    W, H = cols * cell * scale, rows * cell * scale
    img = Image.new("RGB", (W, H), (0, 0, 0))
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, W - 1, H - 1], radius=int(min(W, H) * radius), fill=255)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, H], fill=SURFACE)
    P = cell * scale
    for j, row in enumerate(grid):
        for i, c in enumerate(row):
            if not c:
                continue
            x0, y0 = (i + pad) * P, (j + pad) * P
            col = colour(c)
            if not c.startswith(("q", "f:")):
                d.rectangle([x0, y0, x0 + P, y0 + P], fill=mix(tuple(int(v * 0.8) for v in col), alpha))
            r = P * 0.47
            d.ellipse([x0 + P / 2 - r, y0 + P / 2 - r, x0 + P / 2 + r, y0 + P / 2 + r], fill=mix(col, alpha))
    img = img.resize((W // scale, H // scale), Image.LANCZOS)
    bg = Image.new("RGBA", img.size, (0, 0, 0, 0))
    bg.paste(img, (0, 0), mask.resize(img.size, Image.LANCZOS))
    return bg


def font(size: int, bold: bool = False):
    for name in (("NotoSans-Bold.ttf", "DejaVuSans-Bold.ttf") if bold else ("NotoSans-Regular.ttf", "DejaVuSans.ttf")):
        for d in ("/usr/share/fonts/noto", "/usr/share/fonts/TTF", "/usr/share/fonts/truetype/dejavu",
                  "C:/Windows/Fonts"):
            try:
                return ImageFont.truetype(f"{d}/{name}", size)
            except OSError:
                pass
    return ImageFont.load_default()


def gif(frames, path: Path, cell: int = 6, alphas=None):
    imgs = []
    for k, g in enumerate(frames):
        t = tile(g, cell, alpha=alphas[k] if alphas else 1.0)
        key = (255, 0, 255)                                      # GIF has one see-through colour: the corners
        flat = Image.new("RGB", t.size, key)
        flat.paste(t, (0, 0), t.getchannel("A").point(lambda a: 255 if a > 127 else 0))
        q = flat.convert("P", palette=Image.ADAPTIVE, colors=64)
        pal = q.getpalette()
        idx = min(range(len(pal) // 3), key=lambda i: sum(abs(pal[3 * i + c] - key[c]) for c in range(3)))
        q.info["transparency"] = idx
        imgs.append(q)
    imgs[0].save(path, save_all=True, append_images=imgs[1:], duration=1000 // FPS, loop=0, optimize=True,
                 disposal=2, transparency=imgs[0].info["transparency"])


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    job = {"moods": MOODS, "cocoa": COCOA, "work": WORK, "home": HOME}
    sp = speech()
    if sp:
        job.update(pcm=sp[0], sr=sp[1], dur=sp[2], text=LINES)
    res = run_node(job)

    tile(res["mood-neutral"][0], 10).save(OUT / "ray.png", optimize=True)
    for m in MOODS:
        tile(res[f"mood-{m}"][0], 6).save(OUT / f"mood-{m}.png", optimize=True)

    # the mood sheet: 4 x 2 tiles with their names
    tiles = [tile(res[f"mood-{m}"][0], 5) for m in MOODS]
    tw, th = tiles[0].size
    gap, label = 18, 34
    sheet = Image.new("RGBA", (4 * tw + 5 * gap, 2 * (th + label) + 3 * gap), (0, 0, 0, 0))
    d = ImageDraw.Draw(sheet)
    f = font(20)
    for k, (m, t) in enumerate(zip(MOODS, tiles)):
        x, y = gap + (k % 4) * (tw + gap), gap + (k // 4) * (th + label + gap)
        sheet.paste(t, (x, y), t)
        name = "goodbye" if m == "warm" else m
        d.text((x + tw / 2, y + th + 8), name, fill=MUTED, font=f, anchor="mt")
    sheet.save(OUT / "moods.png", optimize=True)

    gif(res["thinking"], OUT / "thinking.gif")
    if "talking" in res:
        gif(res["talking"], OUT / "talking.gif")
    gif([g for g, _ in res["goodbye"]], OUT / "goodbye.gif", alphas=[a for _, a in res["goodbye"]])
    for name in [f"cocoa-{c}" for c in COCOA] + [f"work-{w}" for w in WORK] + [f"home-{h}" for h in HOME]:
        gif(res[name], OUT / f"{name}.gif")

    # social preview: Ray at the left, the name and a line at the right
    W, H = 1280, 640
    soc = Image.new("RGB", (W, H), (11, 13, 16))
    t = tile(res["mood-neutral"][0], 11)
    soc.paste(t, (90, (H - t.size[1]) // 2), t)
    d = ImageDraw.Draw(soc)
    x = 90 + t.size[0] + 70
    d.text((x, 190), "Ray", fill=TEXT, font=font(120, bold=True))
    d.text((x, 345), "The household's little red panda", fill=(244, 164, 110), font=font(36))
    d.text((x, 395), "and private AI assistant.", fill=(244, 164, 110), font=font(36))
    d.text((x, 470), "One PC, a local model. Built on Strata.", fill=MUTED, font=font(28))
    soc.save(OUT / "social.png", optimize=True)

    print("wrote", ", ".join(sorted(p.name for p in OUT.iterdir())), "in", OUT.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
