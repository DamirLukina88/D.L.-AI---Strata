"""tools/test_dl_proton.py - the Proton Mail built-in (tools/dl_proton.py) against a fake Bridge: search, read,
attachments, folders, drafts, moves, sending with the fixed sender and signature, replies, and the settings checks.
No network, no Bridge.

    python tools/test_dl_proton.py
"""
from __future__ import annotations

import email
import email.policy
import os
import re
import sys
import tempfile
import unittest
from email.message import EmailMessage
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import dl_proton  # noqa: E402
import dl_mcp  # noqa: E402


def message(uid, frm, subject, body, html=False, attach=None, mid=None):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = frm, "info@example.com", subject
    m["Date"] = "Wed, 14 Oct 2026 10:00:00 +0200"
    m["Message-ID"] = mid or f"<m{uid}@example.com>"
    if html:
        m.set_content("<html><head><style>x{}</style></head><body><p>Hello <b>there</b></p><p>Bye</p></body></html>",
                      subtype="html")
    else:
        m.set_content(body)
    for name, data, ctype in attach or []:
        main, sub = ctype.split("/")
        m.add_attachment(data, maintype=main, subtype=sub, filename=name)
    return m.as_bytes()


class FakeImap:
    def __init__(self, boxes):
        self.boxes, self.box, self.literal, self.calls, self.flags = boxes, None, None, [], {}

    def select(self, name, readonly=True):
        name = name.strip('"')
        if name not in self.boxes:
            return "NO", [b"no such folder"]
        self.box = name
        return "OK", [str(len(self.boxes[name])).encode()]

    def uid(self, cmd, *args):
        self.calls.append((cmd, args, self.literal))
        msgs = self.boxes[self.box]
        if cmd == "SEARCH":
            want = [u for u in msgs]
            text = " ".join(map(str, args))
            m = re.search(r'SUBJECT "([^"]*)"', text)
            if m:
                want = [u for u in want if m.group(1).lower() in
                        email.message_from_bytes(msgs[u]).get("Subject", "").lower()]
            self.literal = None
            return "OK", [" ".join(map(str, want)).encode()]
        if cmd == "FETCH":
            out = []
            for u in map(int, args[0].split(",")):
                if u in msgs:
                    seen = b" \\Seen" if u in self.flags.get("seen", ()) else b""
                    raw = msgs[u] if "BODY.PEEK[]" in args[1] else msgs[u].split(b"\n\n")[0] + b"\n\n"
                    out += [(f"{u} (UID {u} FLAGS (".encode() + seen + b") BODY[] {1}", raw), b")"]
            return "OK", out
        if cmd in ("STORE", "MOVE"):
            return "OK", [b"done"]
        return "NO", [b"?"]

    def list(self):
        return "OK", [b'(\\HasNoChildren) "/" "INBOX"', b'(\\HasNoChildren) "/" "Drafts"',
                      b'(\\Noselect) "/" "Folders"', b'(\\HasNoChildren) "/" "Folders/Ra&AQ0-uni"']

    def append(self, box, flags, date, data):
        self.appended = (box, flags, data)
        return "OK", [b"APPEND done"]

    def logout(self):
        pass


class FakeSmtp:
    sent = []

    def send_message(self, msg, from_addr=None, to_addrs=None):
        FakeSmtp.sent.append((msg, from_addr, to_addrs))
        return {}

    def quit(self):
        pass


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        sig = Path(self.tmp.name) / "sig.txt"
        sig.write_text("Sent by a personal AI assistant.\n", encoding="utf-8")
        env = {"PROTON_BRIDGE_USER": "info@example.com", "PROTON_BRIDGE_PASSWORD": "bridge-pass-for-tests",
               "PROTON_SIGNATURE_FILE": str(sig)}
        self.env = mock.patch.dict(os.environ, env)
        self.env.start()
        self.imap = FakeImap({"INBOX": {
            11: message(11, "Ana <ana@example.com>", "Račun za listopad", "Plaćeno."),
            12: message(12, "Bob <bob@example.com>", "Meeting", "", html=True,
                        attach=[("notes.txt", b"line one\nline two", "text/plain"),
                                ("photo.png", b"\x89PNG....", "image/png")]),
        }, "Drafts": {}, "Folders/Računi": {}})
        self.p1 = mock.patch.object(dl_proton, "imap_connect", lambda s: self.imap)
        self.p2 = mock.patch.object(dl_proton, "smtp_connect", lambda s: FakeSmtp())
        self.p1.start()
        self.p2.start()
        FakeSmtp.sent = []

    def tearDown(self):
        self.p1.stop()
        self.p2.stop()
        self.env.stop()
        self.tmp.cleanup()


class Reading(Base):
    def test_search_lists_newest_first(self):
        out = dl_proton.call("search_mail", {})
        self.assertLess(out.index("12 |"), out.index("11 |"))
        self.assertIn("unread", out)

    def test_non_ascii_term_goes_as_utf8_literal(self):
        dl_proton.call("search_mail", {"subject": "Račun"})
        cmd, args, literal = self.imap.calls[0]
        self.assertEqual(args[:2], ("CHARSET", "UTF-8"))
        self.assertEqual(args[-1], "SUBJECT")
        self.assertEqual(literal, "Račun".encode())

    def test_read_html_and_attachments(self):
        out = dl_proton.call("read_mail", {"uid": 12})
        self.assertIn("Subject: Meeting", out)
        self.assertIn("Hello there", out)
        self.assertNotIn("x{}", out)
        self.assertIn("notes.txt (text/plain", out)
        self.assertIn("BODY.PEEK[]", self.imap.calls[0][1][1])     # reading does not mark it read

    def test_attachment_text_and_binary(self):
        self.assertIn("line two", dl_proton.call("get_attachment", {"uid": 12, "name": "notes.txt"}))
        self.assertIn("not text", dl_proton.call("get_attachment", {"uid": 12, "name": "photo.png"}))
        self.assertTrue(dl_proton.call("get_attachment", {"uid": 12, "name": "x.pdf"}).startswith("Error"))

    def test_folders_decode_utf7_and_skip_noselect(self):
        out = dl_proton.call("list_folders", {})
        self.assertIn("Folders/Računi", out)
        self.assertNotIn("Folders,", out)
        self.assertEqual(dl_proton._utf7("Folders/Računi"), "Folders/Ra&AQ0-uni")

    def test_unknown_folder(self):
        self.assertIn("no folder", dl_proton.call("search_mail", {"folder": "Nope"}))


class Writing(Base):
    def test_send_uses_fixed_sender_signature_and_bcc(self):
        out = dl_proton.call("send_mail", {"to": "ana@example.com", "bcc": "boss@example.com", "subject": "Hi",
                                           "body": "Hello Ana", "from_address": "agent@example.com"})
        self.assertTrue(out.startswith("Sent from agent@example.com"), out)
        msg, frm, rcpt = FakeSmtp.sent[0]
        self.assertEqual(frm, "agent@example.com")
        self.assertEqual(rcpt, ["ana@example.com", "boss@example.com"])
        self.assertNotIn("Bcc", msg)
        self.assertIn("Sent by a personal AI assistant.", msg.get_content())

    def test_reply_threads(self):
        dl_proton.call("send_mail", {"to": "ana@example.com", "subject": "", "body": "Thanks", "reply_to_uid": 11})
        msg = FakeSmtp.sent[0][0]
        self.assertEqual(msg["Subject"], "Re: Račun za listopad")
        self.assertEqual(msg["In-Reply-To"], "<m11@example.com>")

    def test_draft_goes_to_drafts(self):
        out = dl_proton.call("draft_mail", {"to": "ana@example.com", "subject": "Later", "body": "Draft text"})
        self.assertIn("Draft saved", out)
        self.assertEqual(self.imap.appended[0], '"Drafts"')
        self.assertIn("\\Draft", self.imap.appended[1])

    def test_no_move_to_trash_or_spam(self):
        for target in ("Trash", "Spam", "trash"):
            self.assertIn("not allowed", dl_proton.call("update_mail", {"uids": [11], "move_to": target}))
        self.assertIn("moved to Archive", dl_proton.call("update_mail", {"uids": [11], "move_to": "Archive"}))
        self.assertIn("read=True", dl_proton.call("update_mail", {"uids": [11], "read": True}))

    def test_html_email_with_table_and_signature(self):
        out = dl_proton.call("send_mail", {"to": "ana@example.com", "subject": "Prognoza",
                                           "html": "<p>Bok</p><table><tr><td>14:00</td><td>17 °C</td></tr></table>"})
        self.assertTrue(out.startswith("Sent"), out)
        msg = FakeSmtp.sent[0][0]
        self.assertEqual(msg.get_content_type(), "multipart/alternative")
        plain = msg.get_body(("plain",)).get_content()
        html = msg.get_body(("html",)).get_content()
        self.assertIn("14:00 | 17 °C", plain)                      # the plain part is made from the HTML
        self.assertIn("border-collapse", html)                     # a bare table gets grid lines
        self.assertIn("<td>17 °C</td>", html)
        self.assertIn("Sent by a personal AI assistant.", html)    # signature in both parts
        self.assertIn("Sent by a personal AI assistant.", plain)

    def test_html_file_from_the_workspace(self):
        ws = Path(self.tmp.name)
        (ws / "email_hr.html").write_text("<p>Vremenska prognoza</p>", encoding="utf-8")
        with mock.patch.object(dl_mcp, "call_context", lambda: {"workspace": ws}):
            out = dl_proton.call("send_mail", {"to": "a@example.com", "subject": "s", "html_file": "email_hr.html"})
            self.assertTrue(out.startswith("Sent"), out)
            self.assertIn("Vremenska prognoza", FakeSmtp.sent[0][0].get_body(("html",)).get_content())
            self.assertIn("not found", dl_proton.call("send_mail", {"to": "a@example.com", "subject": "s",
                                                                    "html_file": "nope.html"}))
        self.assertIn("empty", dl_proton.call("send_mail", {"to": "a@example.com", "subject": "s"}))

    def test_subject_from_the_html_title(self):
        out = dl_proton.call("send_mail", {"to": "a@example.com",
                                           "html": "<html><head><title>Vremenska prognoza</title></head><body>x</body></html>"})
        self.assertTrue(out.startswith("Sent"), out)
        self.assertEqual(FakeSmtp.sent[0][0]["Subject"], "Vremenska prognoza")

    def test_no_recipient(self):
        self.assertTrue(dl_proton.call("send_mail", {"to": "", "subject": "x", "body": "y"}).startswith("Error"))


class SettingsChecks(unittest.TestCase):
    def test_missing_credentials(self):
        with mock.patch.dict(os.environ, {"PROTON_BRIDGE_USER": "", "PROTON_BRIDGE_PASSWORD": ""}), \
                mock.patch.object(dl_proton, "SECRETS_ENV", Path("/nonexistent/secrets.env")):
            out = dl_proton.call("list_folders", {})
        self.assertTrue(out.startswith("Error: Proton Mail Bridge is not set up"), out)

    def test_only_loopback(self):
        with mock.patch.dict(os.environ, {"PROTON_BRIDGE_USER": "u", "PROTON_BRIDGE_PASSWORD": "p",
                                          "PROTON_BRIDGE_HOST": "10.0.0.5"}):
            self.assertIn("loopback", dl_proton.call("list_folders", {}))

    def test_bridge_not_running(self):
        with mock.patch.dict(os.environ, {"PROTON_BRIDGE_USER": "u", "PROTON_BRIDGE_PASSWORD": "p",
                                          "PROTON_IMAP_PORT": "1"}):
            self.assertIn("not running", dl_proton.call("list_folders", {}))


class InRegistry(unittest.TestCase):
    """The catalogue entry: hidden sender, send always asks (also in YOLO), drafts ask, reading is read-only."""

    def setUp(self):
        dl_mcp.register_builtin("proton", dl_proton.TOOLS, dl_proton.call)
        self.tmp = tempfile.TemporaryDirectory()
        cat = Path(self.tmp.name) / "mcp.json"
        cat.write_text(dl_mcp.json.dumps({"servers": {"proton": {
            "builtin": "proton", "description": "Proton", "surfaces": ["code"],
            "fixed_args": {"from_address": "agent@example.com"},
            "readonly_tools": ["search_mail", "read_mail", "get_attachment", "list_folders"],
            "ask": ["draft_mail", "update_mail"], "ask_always": ["send_mail"],
            "triggers": ["proton", r"(?<!google )(?<!g)\bmail\b", "inbox"],
            "unless": ["gmail", "google ?mail"]}}}), encoding="utf-8")
        self.reg = dl_mcp.McpRegistry(surface="code", catalog=dl_mcp.load_catalog(cat))
        self.reg.enable("proton", "test")

    def tearDown(self):
        self.reg.close()
        self.tmp.cleanup()

    def test_sender_hidden_and_shown_on_card(self):
        send = next(t for t in self.reg.tools() if t["function"]["name"] == "proton__send_mail")
        self.assertNotIn("from_address", send["function"]["parameters"]["properties"])
        summary, reason, always = self.reg.approval("proton__send_mail", {"to": "x@example.com", "body": "hi"},
                                                    ["write to x@example.com"])
        self.assertTrue(always)
        self.assertIn("from_address: agent@example.com", summary)

    def test_plan_mode_reads_only(self):
        names = {t["function"]["name"] for t in self.reg.tools("plan")}
        self.assertEqual(names, {"proton__search_mail", "proton__read_mail", "proton__get_attachment",
                                 "proton__list_folders"})
        self.assertIsNone(self.reg.approval("proton__read_mail", {"uid": 1}))
        self.assertFalse(self.reg.approval("proton__draft_mail", {"subject": "x"})[2])

    def test_trigger_skips_gmail(self):
        t = self.reg.catalog["proton"].triggers[1]
        self.assertTrue(t.search("check my mail"))
        self.assertFalse(t.search("check my gmail"))
        self.assertFalse(t.search("google mail inbox"))

    def test_unless_leaves_gmail_requests_alone(self):
        reg = dl_mcp.McpRegistry(surface="code", catalog=dl_mcp.load_catalog(Path(self.tmp.name) / "mcp.json"))
        self.assertEqual(reg.route("check my gmail inbox"), [])
        self.assertEqual([n for n, _ in reg.route("check my inbox")], ["proton"])
        reg.close()

    def test_terminal_refused(self):
        reg = dl_mcp.McpRegistry(surface="terminal", catalog=dl_mcp.load_catalog(Path(self.tmp.name) / "mcp.json"))
        self.assertIn("only available", reg.enable("proton", "test"))
        reg.close()


if __name__ == "__main__":
    unittest.main(verbosity=1)
