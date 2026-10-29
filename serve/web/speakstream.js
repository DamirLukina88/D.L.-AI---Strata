// serve/web/speakstream.js - Ray speaks a spoken prompt's reply sentence by sentence while the model writes it, instead
// of after the whole turn.  SpeakStream takes the reply's text as it arrives and hands out pieces ready to be spoken:
//   - a piece ends at a sentence end (. ! ? or a blank line) that is followed by more text, outside any code block
//     still open; pieces under 40 characters wait to be joined to the next sentence (the first after each tool call,
//     and the turn's first, may be 24: it starts the voice), so each Piper request is worth its overhead
//   - a "note" is text that a tool call follows ("Let me check the printer…").  Only its first piece is spoken; what
//     is queued after it is dropped when the tool call arrives
//   - one note every 15 s at most: after a spoken note, the next text is held until 15 s have passed (then it is
//     spoken) or the turn ends (it was the answer: spoken in full) or a tool call comes (another note: dropped)
// It knows nothing of audio: say(text) queues a piece, drop(n) keeps only the first n pieces of the current note.
// On a spoken prompt the model writes one short sentence about the action before its first tool call (VOICE_NOTE in
// tools/dl_cli.py), so that note is what fills the wait.  Canned filler lines and a soft "thinking" sound were tried
// on 2026-10-29 and dropped: the user found them unnatural.
// Pure, so tools/test_speakstream.py runs it in node.
"use strict";

class SpeakStream {
  constructor({say, drop, now = () => Date.now(), min = 40, minFirst = 24, noteGap = 15000} = {}) {
    Object.assign(this, {say, drop, now, min, minFirst, noteGap});
    this.buf = "";              // text not yet handed out
    this.held = [];             // pieces held back by the note guard
    this.spoken = 0;            // pieces handed out in this turn
    this.segSpoken = 0;         // ... in the current segment (the text since the last tool call)
    this.noteAt = -Infinity;    // when the last note was spoken
    this.ended = false;
  }

  // new reply text arrived
  push(text) {
    if (this.ended || !text) return;
    this.buf += text;
    this._release(false);
  }

  // a tool call: the text before it was a note, and it is complete (a preamble often ends just before the call, with
  // nothing after its full stop, so it is let out here; the note guard still applies)
  tool() {
    if (this.ended) return;
    if (this.segSpoken === 0) {
      const piece = this.buf.trim();
      this.buf = "";
      if (piece) this.held.push(piece);
      if (this.now() - this.noteAt >= this.noteGap) this._flushHeld();
    }
    if (this.segSpoken > 0) {
      this.drop(1);             // keep its first piece only
      this.noteAt = this.now();
    }
    this.buf = ""; this.held = []; this.segSpoken = 0;
  }

  // the turn ended: everything left is the answer
  end() {
    if (this.ended) return;
    this._release(true);
    this.ended = true;
  }

  // the note guard's 15 s may have passed while nothing new arrived
  tick() {
    if (!this.ended && this.held.length && this.now() - this.noteAt >= this.noteGap) this._flushHeld();
  }

  _release(final) {
    for (;;) {
      const piece = this._take(final);
      if (piece == null) break;
      this.held.push(piece);
    }
    if (final || this.now() - this.noteAt >= this.noteGap) this._flushHeld();
  }

  _flushHeld() {
    for (const p of this.held) { this.say(p); this.spoken++; this.segSpoken++; }
    this.held = [];
  }

  // the next piece of the buffer that is ready, or null; at the end, all that is left
  _take(final) {
    const min = this.segSpoken + this.held.length === 0 ? this.minFirst : this.min;   // the first of each segment may be short
    let cut = -1;
    const re = /([.!?]["')\]]*)(\s)|(\n\s*\n)/g;
    for (let m; (m = re.exec(this.buf));) {
      const end = m.index + (m[1] ? m[1].length : m[0].length);
      const head = this.buf.slice(0, end);
      if ((head.match(/```/g) || []).length % 2) continue;             // inside a code block still open
      if (m[1] && /\b(e\.g|i\.e|vs|dr|mr|mrs|ms|etc|approx)\.$/i.test(head)) continue;
      if (m[1] && /\d\.$/.test(head) && /^\s*\d/.test(this.buf.slice(end))) continue;
      if (head.trim().length < min) continue;                         // too short: join it to the next sentence
      cut = end;
      break;
    }
    if (cut < 0) {
      if (!final || !this.buf.trim()) return null;
      cut = this.buf.length;
    }
    const piece = this.buf.slice(0, cut).trim();
    this.buf = this.buf.slice(cut);
    return piece || (final ? null : this._take(final));
  }
}

if (typeof module !== "undefined") module.exports = {SpeakStream};
