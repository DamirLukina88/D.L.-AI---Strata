"""ray_speech_latency.py - how soon Ray's voice starts on a spoken prompt: after the whole reply (the old way), or
sentence by sentence while the reply is written (serve/web/speakstream.js), where a short sentence before a tool call
(the preamble VOICE_NOTE asks for) is heard while the tool runs.

    python3 tools/ray_speech_latency.py [--socket PATH] [--save FILE | --load FILE] ["prompt" ...]

Sends each prompt to the running dl-ai-sessiond as a spoken prompt (as the web app does) and records when each piece of
the reply's text and each tool call arrived (--save keeps the recording, --load replays one without the model).  Then
it plays the turn back in node through the web app's own code (cleanForSpeech and chunkText from serve/web/app.js, and
speakstream.js) on a fake clock, with Piper's time and the audio's length from a fit measured here on serve/speech.py
at the web app's default pace (rate 1, pitch 1.5):

    after the reply      the last reply's first 240-character chunk, made once the turn ends
    while it is written  pieces queued as SpeakStream hands them out, each made by Piper, played one after another

Reported, from sending the prompt: Ray's first word either way (a preamble counts), the answer's first word, and the
longest silence before the answer's first word.  Not counted: the
browser's fetch and decode (a few ms on the same PC) and the phone network.
"""
from __future__ import annotations

import argparse
import json
import queue
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "serve"))
import dl_agent_bench as bench  # noqa: E402
import dl_sessiond  # noqa: E402
import speech  # noqa: E402

PROMPTS = ["what's the capital of Croatia and what is it known for",
           "how warm is it in Zagreb right now",
           "hey Ray, tell me a fun fact about red pandas"]
PITCH = 1.5

# node: play a recorded turn back through the web app's speech code on a fake clock (50 ms steps)
NODE = r"""
const fs = require("fs");
const app = fs.readFileSync(process.argv[1], "utf8");
const a = app.indexOf("function cleanForSpeech("), b = app.indexOf("function chunkText(");
const c = app.indexOf("\n}\n", b) + 3;
eval(app.slice(a, c).replace("function cleanForSpeech(", "globalThis.cleanForSpeech = function(")
                    .replace("function chunkText(", "globalThis.chunkText = function("));
const {SpeakStream} = require(process.argv[2]);
const {rec, fit} = JSON.parse(fs.readFileSync(0, "utf8"));
const lat = (s) => fit.a + fit.b * s.length, dur = (s) => fit.c * s.length + fit.d;

function play(mode) {
  let now = 0, ended = false, seg = 0, segStart = 0;
  const queue = [], played = [];
  let playing = null;
  // pieces as TTSController queues them; each knows its segment (the text since the last tool call)
  const push = (text) => { for (const s of chunkText(cleanForSpeech(text), 240)) queue.push({text: s, seg, at: now}); };
  const ss = mode === "whole" ? null : new SpeakStream({
    now: () => now * 1000,
    say: (p) => { if (ss.segSpoken === 0) segStart = played.length + queue.length; push(p); },
    // a note keeps its first `keep` pieces: drop the later ones still waiting (as TTSController.streamDrop)
    drop: (keep) => { const n = segStart + keep - played.length; if (queue.length > n) queue.length = Math.max(0, n); },
  });
  const evs = rec.events.slice();
  for (let k = 0; now < rec.end + 120; k++) {
    now = k * 0.05;
    while (evs.length && evs[0].t <= now) {
      const ev = evs.shift();
      if (ev.type === "tool_call") seg++;
      if (!ss) continue;
      if (ev.type === "text") ss.push(ev.text); else ss.tool();
    }
    if (!ended && now >= rec.end) {
      ended = true;
      if (ss) ss.end();
      else push(rec.events.filter((e) => e.type === "text" && e.seg === rec.lastSeg).map((e) => e.text).join(""));
    }
    if (ss) ss.tick();
    if (playing && now >= playing.end) playing = null;
    if (!playing && queue.length) {
      const p = queue.shift(), start = Math.max(now, p.at + lat(p.text));
      playing = {...p, start, end: start + dur(p.text)};
      played.push(playing);
    }
    if (ended && !playing && !queue.length) break;
  }
  const first = played.length ? played[0].start : null;
  const ans = played.find((p) => p.seg === rec.lastSeg);
  const answer = ans ? ans.start : null;
  let silence = 0, from = 0;
  for (const p of played) {
    if (answer === null || p.start > answer) break;
    silence = Math.max(silence, p.start - from);
    from = Math.max(from, p.end);
  }
  return {first, answer, silence, preambles: played.filter((p) => p.seg < rec.lastSeg).map((p) => p.text)};
}
process.stdout.write(JSON.stringify({whole: play("whole"), stream: play("stream")}));
"""


def record(live: bench.Live, prompt: str, timeout: float = 300) -> dict:
    """one spoken prompt: every text and tool call with its time since sending, and the turn's end"""
    t0 = time.time()
    live.send(op="input", text=prompt, origin="bench", voice=True)
    events, seg = [], 0
    while True:
        try:
            ev = live.q.get(timeout=1)
        except queue.Empty:
            if time.time() - t0 > timeout:
                raise TimeoutError(prompt)
            continue
        t = ev.get("type")
        if t == "text":
            events.append({"type": "text", "text": ev.get("text", ""), "t": time.time() - t0, "seg": seg})
        elif t == "tool_call":
            seg += 1
            events.append({"type": "tool_call", "name": ev.get("name"), "args": ev.get("args") or {}, "t": time.time() - t0})
        elif t in ("turn_end", "_closed", "error"):
            return {"prompt": prompt, "events": events, "end": time.time() - t0, "lastSeg": seg}


def piper_fit() -> dict:
    """Piper's time to make a piece, a + b x characters, and the audio's length at pitch 1.5, c x characters + d"""
    texts = ["One sec, checking.", "Hmm, let me think about that one for you.",
             "The capital of Croatia is Zagreb, a city of around 800,000 people on the Sava river.",
             "Right now it is twelve degrees in Zagreb, and with the wind it feels more like nine. Tonight it drops to "
             "six, and tomorrow should be a little warmer with some sun in the afternoon, so take a light jacket."]
    speech.synthesize("Warming up the voice.", speed=1 / PITCH)
    pts = []
    for s in texts:
        t = time.perf_counter()
        wav = speech.synthesize(s, speed=1 / PITCH)
        pts.append((len(s), time.perf_counter() - t, (len(wav) - 44) / (22050 * 2) / PITCH))

    def line(xs, ys):
        mx, my = statistics.mean(xs), statistics.mean(ys)
        k = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
        return k, my - k * mx

    b, a = line([p[0] for p in pts], [p[1] for p in pts])
    c, d = line([p[0] for p in pts], [p[2] for p in pts])
    return {"a": a, "b": b, "c": c, "d": d, "points": pts}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--socket", default=str(dl_sessiond.SOCKET_PATH))
    ap.add_argument("--save", default="", help="keep the recordings in this JSON file")
    ap.add_argument("--load", default="", help="replay recordings from this JSON file instead of asking the model")
    ap.add_argument("prompts", nargs="*")
    a = ap.parse_args()
    fit = piper_fit()
    print(f"Piper: {fit['a']:.2f} s + {fit['b'] * 100:.2f} s per 100 characters to make; "
          f"{fit['c'] * 100:.2f} s of speech per 100 characters", flush=True)
    if a.load:
        recs = json.loads(Path(a.load).read_text())
    else:
        recs = []
        for k, prompt in enumerate(a.prompts or PROMPTS):
            live = bench.Live(f"speech-latency-{int(time.time())}-{k}", Path(a.socket))
            try:
                live.send(op="input", text="/clear", origin="bench")
                time.sleep(1)
                while not live.q.empty():
                    live.q.get()
                recs.append(record(live, prompt))
            finally:
                live.close()
            print(f"recorded {prompt!r}: turn {recs[-1]['end']:.1f} s", flush=True)
        if a.save:
            Path(a.save).write_text(json.dumps(recs, indent=1, ensure_ascii=False))
    print("\n| Prompt | Tool calls | Turn | Answer's first word, after the reply | First word, while written | "
          "Answer's first word, while written | Longest silence before the answer | Preamble spoken |")
    print("| :-- | --: | --: | --: | --: | --: | --: | :-- |")
    for rec in recs:
        r = json.loads(subprocess.run(["node", "-e", NODE, str(ROOT / "serve/web/app.js"), str(ROOT / "serve/web/speakstream.js")],
                                      input=json.dumps({"rec": rec, "fit": fit}), capture_output=True, text=True,
                                      check=True).stdout)
        n = sum(1 for e in rec["events"] if e["type"] == "tool_call")
        f = lambda v: f"{v:.1f} s" if v is not None else "-"  # noqa: E731
        print(f"| {rec['prompt']} | {n} | {rec['end']:.1f} s | {f(r['whole']['answer'])} | {f(r['stream']['first'])} | "
              f"{f(r['stream']['answer'])} | {f(r['stream']['silence'])} | {' / '.join(r['stream']['preambles']) or '-'} |",
              flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
