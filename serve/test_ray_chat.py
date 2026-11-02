"""/v1/ray/chat (the Ray Android app's voice drawer) over a fake session daemon: the answer arrives as content, the
model's thinking as reasoning_content and a tool call as ray_tool, so the drawer can show each.

Run from the repo root: python -m unittest serve.test_ray_chat
"""
import json
import socket
import sys
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import serve.server as server  # noqa: E402
from serve.frontend import ChatTemplate  # noqa: E402
from serve.server import ByteTokenizer, MockEngine, Service, serve  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

# what dl_sessiond sends for one turn, in order
TURN = [
    {"type": "user", "text": "hi"},
    {"type": "thinking", "text": "The user says hi. "},
    {"type": "thinking", "text": "Check the battery first."},
    {"type": "tool_call", "id": "c1", "name": "phone__phone_get_battery", "args": {}},
    {"type": "tool_result", "id": "c1", "text": "80%"},
    {"type": "text", "text": "Hi! "},
    {"type": "text", "text": "Your battery is at 80%."},
    {"type": "turn_end"},
]


class FakeSessiond:
    """A Unix socket that answers attach with hello and an input with TURN, recording what it was sent."""

    def __init__(self, path: Path):
        self.path = path
        self.received = []
        self.sock = socket.socket(socket.AF_UNIX)
        self.sock.bind(str(path))
        self.sock.listen(4)
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._client, args=(conn,), daemon=True).start()

    def _client(self, conn):
        with conn, conn.makefile("rb") as f:
            for line in f:
                op = json.loads(line)
                self.received.append(op)
                if op.get("op") == "attach":
                    conn.sendall(b'{"type": "hello"}\n')
                elif op.get("op") == "input":
                    for ev in TURN:
                        conn.sendall((json.dumps(ev) + "\n").encode())

    def close(self):
        self.sock.close()


class RayChatStream(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.sessiond = FakeSessiond(Path(cls.tmp.name) / "sessiond.sock")
        cls.patch = mock.patch.object(server, "SESSIOND_SOCKET", cls.sessiond.path)
        cls.patch.start()
        tok = ByteTokenizer()
        cls.httpd = serve(Service(MockEngine(tok, "ok", max_context=4096), tok,
                                  ChatTemplate(ROOT / "serve/chat_template.jinja")), port=0)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.patch.stop()
        cls.sessiond.close()
        cls.tmp.cleanup()

    def chunks(self, body):
        req = urllib.request.Request(self.base + "/v1/ray/chat", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", "Accept": "text/event-stream"})
        out = []
        with urllib.request.urlopen(req, timeout=30) as r:
            for raw in r:
                line = raw.decode().strip()
                if not line.startswith("data: "):
                    continue
                data = line[len("data: "):]
                if data == "[DONE]":
                    out.append("[DONE]")
                    break
                out.append(json.loads(data))
        return out

    def test_answer_thinking_and_tool_calls_are_told_apart(self):
        out = self.chunks({"messages": [{"role": "user", "content": "hi"}], "stream": True, "voice": True})
        self.assertEqual(out[-1], "[DONE]")
        deltas = [c["choices"][0]["delta"] for c in out[:-1]]
        self.assertEqual("".join(d.get("content", "") for d in deltas), "Hi! Your battery is at 80%.")
        self.assertEqual("".join(d.get("reasoning_content", "") for d in deltas),
                         "The user says hi. Check the battery first.")
        self.assertEqual([c["ray_tool"]["name"] for c in out[:-1] if "ray_tool" in c], ["phone__phone_get_battery"])
        # the order holds: thinking, then the tool, then the answer
        kinds = ["think" if "reasoning_content" in d else "tool" if "ray_tool" in c else "text"
                 for c, d in zip(out[:-1], deltas)]
        self.assertEqual(kinds, ["think", "think", "tool", "text", "text"])
        # the prompt reached the session as a spoken one from the Android app
        sent = [op for op in self.sessiond.received if op.get("op") == "input"][-1]
        self.assertEqual((sent["text"], sent["voice"], sent["origin"]), ("hi", True, "ray-android"))


if __name__ == "__main__":
    unittest.main()
