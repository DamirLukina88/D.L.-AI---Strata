"""tools/test_speakstream.py - serve/web/speakstream.js (Ray reads a reply sentence by sentence while it is written),
run in node with a fake clock.  No GPU, no server.

    python tools/test_speakstream.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

JS = Path(__file__).resolve().parent.parent / "serve" / "web" / "speakstream.js"

# a script of steps -> what was said, and every drop(keep), in order
RUNNER = r"""
const {SpeakStream} = require(process.argv[1]);
const steps = JSON.parse(process.argv[2]);
let t = 0;
const out = [];
const ss = new SpeakStream({say: (p) => out.push(p), drop: (k) => out.push(["drop", k]), now: () => t});
for (const [op, arg] of steps) {
  if (op === "push") ss.push(arg);
  else if (op === "tool") ss.tool();
  else if (op === "end") ss.end();
  else if (op === "wait") { t += arg; ss.tick(); }
}
process.stdout.write(JSON.stringify(out));
"""


def run(*steps) -> list:
    r = subprocess.run(["node", "-e", RUNNER, str(JS), json.dumps(steps)], capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


@unittest.skipUnless(shutil.which("node"), "needs node")
class SpeakStreamTest(unittest.TestCase):
    def test_first_sentence_goes_at_once(self):
        out = run(["push", "The kitchen light is on now. "], ["push", "Anything else"])
        self.assertEqual(out, ["The kitchen light is on now."])

    def test_needs_the_next_character(self):
        # "on now." could still be "on now.5": a sentence ends only once the text after it has started
        self.assertEqual(run(["push", "The kitchen light is on now."]), [])

    def test_short_sentences_are_joined(self):
        out = run(["push", "Sure thing! Done. The living room lights are off and the plug is on. "], ["end"])
        self.assertEqual(out, ["Sure thing! Done. The living room lights are off and the plug is on."])

    def test_later_pieces_need_40(self):
        out = run(["push", "The kitchen light is on now. Okay. It is 21 degrees inside and 9 outside. "], ["end"])
        self.assertEqual(out, ["The kitchen light is on now.", "Okay. It is 21 degrees inside and 9 outside."])

    def test_abbreviations_and_decimals_do_not_split(self):
        out = run(["push", "Use a light colour, e.g. warm white at 3.5 W per bulb. "], ["push", "x"], ["end"])
        self.assertEqual(out[0], "Use a light colour, e.g. warm white at 3.5 W per bulb.")

    def test_code_block_waits_until_closed(self):
        out = run(["push", "Here is the fix for the parser.\n```python\nx = 1. y = 2. z = 3. w = 4. v = 5. "])
        self.assertEqual(out, ["Here is the fix for the parser."])     # nothing from inside the open fence
        out = run(["push", "Here is the fix for the broken parser loop.\n```python\nx = 1. y = 2.\n```\nThat is all. "],
                  ["end"])
        self.assertEqual(out[0], "Here is the fix for the broken parser loop.")
        self.assertIn("```python\nx = 1. y = 2.\n```", "".join(out[1:]))

    def test_end_flushes_the_rest(self):
        out = run(["push", "It is sunny and 18 degrees in Zagreb right now"], ["end"])
        self.assertEqual(out, ["It is sunny and 18 degrees in Zagreb right now"])

    def test_a_note_keeps_its_first_piece(self):
        out = run(["push", "Let me check the printer for you first. Then I will look at the kitchen camera as well. "],
                  ["tool"])
        self.assertEqual(out, ["Let me check the printer for you first.", "Then I will look at the kitchen camera as well.",
                               ["drop", 1]])

    def test_answer_after_a_tool_may_start_short(self):
        out = run(["push", "Let me check Wikipedia for that."], ["tool"], ["wait", 20000],
                  ["push", "The capital of Croatia is Zagreb. It sits on the Sava river. "])
        self.assertEqual(out[-1], "The capital of Croatia is Zagreb.")

    def test_preamble_right_before_a_tool_is_spoken(self):
        # nothing follows its full stop but the tool call: it is still complete, and short ones count too
        out = run(["push", "Let me check the live weather for Zagreb."], ["tool"])
        self.assertEqual(out, ["Let me check the live weather for Zagreb.", ["drop", 1]])
        self.assertEqual(run(["push", "One moment."], ["tool"]), ["One moment.", ["drop", 1]])

    def test_one_note_per_15_s(self):
        out = run(["push", "Let me check the printer for you first. "], ["tool"],
                  ["push", "Now the camera, one moment please. "], ["tool"],           # within 15 s: dropped
                  ["push", "The printer is idle and the camera shows the bed. "], ["end"])
        self.assertEqual(out, ["Let me check the printer for you first.", ["drop", 1],
                               "The printer is idle and the camera shows the bed."])

    def test_held_text_goes_after_15_s(self):
        out = run(["push", "Let me check the printer for you first. "], ["tool"],
                  ["push", "The printer is printing a bracket right now. And more. "], ["wait", 14000])
        self.assertEqual(out, ["Let me check the printer for you first.", ["drop", 1]])
        out = run(["push", "Let me check the printer for you first. "], ["tool"],
                  ["push", "The printer is printing a bracket right now. And more. "], ["wait", 15000])
        self.assertEqual(out[-1], "The printer is printing a bracket right now.")

    def test_nothing_after_end(self):
        self.assertEqual(run(["end"], ["push", "Late text that arrives after the turn. "]), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
