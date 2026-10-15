"""tools/dl_proton.py - Proton Mail for D.L. CLI through Proton Mail Bridge (IMAP and SMTP on 127.0.0.1).

Standard library only, run in process as the built-in "proton" (mcp.json: {"builtin": "proton"}), so no outside
code sees the Bridge password.  Settings come from the environment or ~/.config/dl-ai/secrets.env, read fresh on
every call:

    PROTON_BRIDGE_USER       the Bridge IMAP/SMTP user name (protonmail-bridge-core --cli, then `info`)
    PROTON_BRIDGE_PASSWORD   the Bridge password from the same `info` (not the Proton account password)
    PROTON_BRIDGE_HOST       default 127.0.0.1; only a loopback address is accepted
    PROTON_IMAP_PORT         default 1143 (STARTTLS)
    PROTON_SMTP_PORT         default 1025 (STARTTLS)

The sending address is the hidden argument `from_address` (mcp.json fixed_args), so the model cannot pick another
identity; Bridge refuses an address that is not on the account.  Bridge does not add the Proton signature, so
send_mail and draft_mail append ~/.config/dl-ai/proton-signature.txt (PROTON_SIGNATURE_FILE) themselves.
"""
from __future__ import annotations

import base64
import email
import email.policy
import email.utils
import imaplib
import ipaddress
import os
import re
import smtplib
import ssl
import time
from email.message import EmailMessage
from html.parser import HTMLParser
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "dl-ai"
SECRETS_ENV = CONFIG_DIR / "secrets.env"
SIGNATURE_FILE = CONFIG_DIR / "proton-signature.txt"
BRIDGE_CERT = Path.home() / ".config" / "protonmail" / "bridge-v3" / "cert.pem"
TIMEOUT = 30
MAX_LIST = 50
MAX_BODY = 20000
NO_MOVE = {"trash", "spam"}          # the user chose no deleting; Trash and Spam are where deleting starts

_ADDR = {"type": "string", "description": "One address or several, comma-separated"}
_UID = {"type": "integer", "description": "Message UID from search_mail"}
_FOLDER = {"type": "string", "description": "Folder, default INBOX (list_folders shows the names)"}
_CONTENT = {"body": {"type": "string", "description": "Plain-text body"},
            "html": {"type": "string", "description": "HTML body (tables, links)"},
            "html_file": {"type": "string", "description": "An .html file in the workspace to use as the HTML body "
                                                           "(read when the email is sent), instead of `html`"}}
TOOLS = [
    {"name": "search_mail", "description": "Search Proton Mail. Returns UID, date, sender and subject, newest first.",
     "inputSchema": {"type": "object", "properties": {
         "query": {"type": "string", "description": "Words in the subject or body"},
         "sender": {"type": "string"}, "recipient": {"type": "string"}, "subject": {"type": "string"},
         "since": {"type": "string", "description": "YYYY-MM-DD"}, "before": {"type": "string", "description": "YYYY-MM-DD"},
         "unread": {"type": "boolean"}, "folder": _FOLDER,
         "limit": {"type": "integer", "description": f"Default 20, at most {MAX_LIST}"}}}},
    {"name": "read_mail", "description": "Read one message: headers, text and attachment names. Does not mark it read.",
     "inputSchema": {"type": "object", "properties": {"uid": _UID, "folder": _FOLDER}, "required": ["uid"]}},
    {"name": "get_attachment", "description": "Read a text attachment (txt, csv, md, json, html, xml, ics, eml) of a message.",
     "inputSchema": {"type": "object", "properties": {
         "uid": _UID, "folder": _FOLDER, "name": {"type": "string", "description": "File name from read_mail"}},
         "required": ["uid", "name"]}},
    {"name": "list_folders", "description": "List the Proton Mail folders and labels.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "draft_mail", "description": "Save a draft in Drafts (not sent). Same content parameters as send_mail; "
                                          "the signature is added automatically.",
     "inputSchema": {"type": "object", "properties": {
         "to": _ADDR, "cc": _ADDR, "bcc": _ADDR, "subject": {"type": "string"}, **_CONTENT,
         "reply_to_uid": {"type": "integer", "description": "UID of the message this answers (in `folder`)"},
         "folder": _FOLDER}}},
    {"name": "update_mail", "description": "Move messages to another folder or mark them read/unread or starred. "
                                           "Cannot move to Trash or Spam.",
     "inputSchema": {"type": "object", "properties": {
         "uids": {"type": "array", "items": {"type": "integer"}}, "folder": _FOLDER,
         "move_to": {"type": "string"}, "read": {"type": "boolean"}, "starred": {"type": "boolean"}},
         "required": ["uids"]}},
    {"name": "send_mail", "description": "Send an email from the assistant's Proton address. Give `body` (plain text) "
                                         "and/or `html` / `html_file` (an HTML email, e.g. with a table; the plain-text "
                                         "part is made from it). Without `subject` the HTML <title> is the subject, so a "
                                         "translated HTML email carries its translated subject. The signature is added "
                                         "automatically. For a reply give reply_to_uid.",
     "inputSchema": {"type": "object", "properties": {
         "to": _ADDR, "cc": _ADDR, "bcc": _ADDR, "subject": {"type": "string"}, **_CONTENT,
         "reply_to_uid": {"type": "integer", "description": "UID of the message this answers (in `folder`)"},
         "folder": _FOLDER}, "required": ["to"]}},
]


class ProtonError(Exception):
    pass


# ---------------------------------------------------------------------- settings
def _secrets_file() -> dict:
    out = {}
    try:
        for line in SECRETS_ENV.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("export "):
                line = line[7:].strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
                v = v[1:-1]
            out[k.strip()] = v
    except OSError:
        pass
    return out


def settings() -> dict:
    file = _secrets_file()
    get = lambda k, d="": os.environ.get(k) or file.get(k) or d  # noqa: E731
    s = {"user": get("PROTON_BRIDGE_USER"), "password": get("PROTON_BRIDGE_PASSWORD"),
         "host": get("PROTON_BRIDGE_HOST", "127.0.0.1"),
         "imap_port": int(get("PROTON_IMAP_PORT", "1143")), "smtp_port": int(get("PROTON_SMTP_PORT", "1025")),
         "signature": Path(os.path.expanduser(get("PROTON_SIGNATURE_FILE", str(SIGNATURE_FILE))))}
    if not s["user"] or not s["password"]:
        raise ProtonError("Proton Mail Bridge is not set up: PROTON_BRIDGE_USER and PROTON_BRIDGE_PASSWORD are "
                          "missing from ~/.config/dl-ai/secrets.env (`protonmail-bridge-core --cli`, then `info`)")
    try:
        loopback = s["host"] == "localhost" or ipaddress.ip_address(s["host"]).is_loopback
    except ValueError:
        loopback = False
    if not loopback:
        raise ProtonError(f"PROTON_BRIDGE_HOST must be a loopback address (Bridge runs on this PC), not {s['host']}")
    return s


def _tls() -> ssl.SSLContext:
    """Bridge has a self-signed certificate: pin it when its file is there, otherwise accept it (loopback only)."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    if BRIDGE_CERT.is_file():
        ctx.load_verify_locations(cafile=str(BRIDGE_CERT))
    else:
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def imap_connect(s: dict):
    try:
        m = imaplib.IMAP4(s["host"], s["imap_port"], timeout=TIMEOUT)
        m.starttls(ssl_context=_tls())
        m.login(s["user"], s["password"])
    except ConnectionRefusedError:
        raise ProtonError(f"Proton Mail Bridge is not running on {s['host']}:{s['imap_port']} "
                          "(systemctl --user start protonmail-bridge)") from None
    except imaplib.IMAP4.error as e:
        raise ProtonError(f"Bridge refused the IMAP login: {e}") from None
    return m


def smtp_connect(s: dict):
    try:
        m = smtplib.SMTP(s["host"], s["smtp_port"], timeout=TIMEOUT)
        m.starttls(context=_tls())
        m.login(s["user"], s["password"])
    except ConnectionRefusedError:
        raise ProtonError(f"Proton Mail Bridge is not running on {s['host']}:{s['smtp_port']} "
                          "(systemctl --user start protonmail-bridge)") from None
    except smtplib.SMTPAuthenticationError as e:
        raise ProtonError(f"Bridge refused the SMTP login: {e.smtp_code}") from None
    return m


# ---------------------------------------------------------------------- IMAP helpers
def _utf7(name: str) -> str:
    """Folder name to IMAP's modified UTF-7 (RFC 3501 5.1.3), so 'Računi' works."""
    out, buf = [], []

    def flush():
        if buf:
            b = base64.b64encode("".join(buf).encode("utf-16-be")).decode().rstrip("=").replace("/", ",")
            out.append("&" + b + "-")
            buf.clear()
    for ch in name:
        if 0x20 <= ord(ch) <= 0x7E:
            flush()
            out.append("&-" if ch == "&" else ch)
        else:
            buf.append(ch)
    flush()
    return "".join(out)


def _unutf7(name: str) -> str:
    def dec(m):
        b = m.group(1)
        if not b:
            return "&"
        b = b.replace(",", "/")
        return base64.b64decode(b + "=" * (-len(b) % 4)).decode("utf-16-be")
    return re.sub(r"&([A-Za-z0-9+,]*)-", dec, name)


def _mailbox(name: str | None) -> str:
    name = (name or "INBOX").strip() or "INBOX"
    return '"' + _utf7(name).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _select(m, folder: str | None, readonly: bool = True) -> None:
    typ, data = m.select(_mailbox(folder), readonly=readonly)
    if typ != "OK":
        raise ProtonError(f"no folder {folder!r} (list_folders shows the names)")


def _date(s: str) -> str:
    try:
        return time.strftime("%d-%b-%Y", time.strptime(s.strip(), "%Y-%m-%d"))
    except ValueError:
        raise ProtonError(f"dates are YYYY-MM-DD, not {s!r}") from None


def _quote(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _header(msg, name: str) -> str:
    return str(msg.get(name) or "").replace("\r", "").replace("\n", " ")


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head"):
            self.skip += 1
        elif tag in ("br", "p", "div", "tr", "li", "h1", "h2", "h3", "blockquote"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head") and self.skip:
            self.skip -= 1
        elif tag in ("td", "th") and not self.skip:      # table cells: "14:00 | 17.1 | Djelomično oblačno"
            self.parts.append(" | ")
        elif tag == "tr" and self.parts and self.parts[-1] == " | ":
            self.parts.pop()

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    p = _Text()
    p.feed(html)
    return re.sub(r"\n\s*\n+", "\n\n", re.sub(r"[ \t]+", " ", "".join(p.parts))).strip()


def _fetch(m, uid: int):
    typ, data = m.uid("FETCH", str(int(uid)), "(BODY.PEEK[])")
    raw = next((d[1] for d in data or [] if isinstance(d, tuple)), None)
    if typ != "OK" or raw is None:
        raise ProtonError(f"no message with UID {uid} in this folder")
    return email.message_from_bytes(raw, policy=email.policy.default)


def _attachments(msg) -> list:
    return [p for p in msg.walk() if p.get_content_disposition() == "attachment" or
            (p.get_filename() and not p.is_multipart())]


# ---------------------------------------------------------------------- tools
def search_mail(m, a: dict) -> str:
    folder = a.get("folder") or "INBOX"
    _select(m, folder)
    crit, local = [], []
    for key, imap in (("sender", "FROM"), ("recipient", "TO"), ("subject", "SUBJECT"), ("query", "TEXT")):
        v = str(a.get(key) or "").strip()
        if not v:
            continue
        if v.isascii():
            crit += [imap, _quote(v)]
        else:
            local.append((key, v.lower()))
    if a.get("since"):
        crit += ["SINCE", _date(str(a["since"]))]
    if a.get("before"):
        crit += ["BEFORE", _date(str(a["before"]))]
    if a.get("unread") is True:
        crit.append("UNSEEN")
    elif a.get("unread") is False:
        crit.append("SEEN")
    # imaplib sends one literal per command: the first non-ASCII term goes to the server, the rest are checked here
    if local:
        key, v = local.pop(0)
        m.literal = str(a[key]).strip().encode("utf-8")
        crit = ["CHARSET", "UTF-8"] + crit + [{"sender": "FROM", "recipient": "TO", "subject": "SUBJECT",
                                                "query": "TEXT"}[key]]
    typ, data = m.uid("SEARCH", *(crit or ["ALL"]))
    if typ != "OK":
        raise ProtonError(f"search failed: {data}")
    uids = sorted((int(x) for x in (data[0] or b"").split()), reverse=True)
    limit = max(1, min(int(a.get("limit") or 20), MAX_LIST))
    rows, scanned = [], 0
    for i in range(0, len(uids), 50):
        chunk = uids[i:i + 50]
        typ, data = m.uid("FETCH", ",".join(map(str, chunk)),
                          "(UID FLAGS BODY.PEEK[HEADER.FIELDS (DATE FROM TO SUBJECT)])")
        heads = {}
        for d in data or []:
            if isinstance(d, tuple):
                uid = re.search(rb"UID (\d+)", d[0])
                if uid:
                    heads[int(uid.group(1))] = (d[0], email.message_from_bytes(d[1], policy=email.policy.default))
        for uid in chunk:
            if uid not in heads:
                continue
            meta, h = heads[uid]
            scanned += 1
            if local and not all(v in _header(h, {"sender": "From", "recipient": "To", "subject": "Subject",
                                                   "query": "Subject"}[k]).lower() for k, v in local):
                continue
            unread = b"\\Seen" not in meta
            rows.append(f"{uid} | {_header(h, 'Date')[:31]} | {_header(h, 'From')[:60]} | "
                        f"{_header(h, 'Subject')[:120]}{' | unread' if unread else ''}")
            if len(rows) >= limit:
                break
        if len(rows) >= limit or scanned >= 500:
            break
    if not rows:
        return f"No messages found in {folder}."
    more = f" (showing {len(rows)} of {len(uids)})" if len(uids) > len(rows) and not local else ""
    return f"{folder}{more}: UID | date | from | subject\n" + "\n".join(rows)


def read_mail(m, a: dict) -> str:
    _select(m, a.get("folder"))
    msg = _fetch(m, a["uid"])
    lines = [f"{h}: {_header(msg, h)}" for h in ("From", "To", "Cc", "Date", "Subject") if msg.get(h)]
    body = msg.get_body(preferencelist=("plain", "html"))
    text = ""
    if body is not None:
        text = body.get_content()
        if body.get_content_type() == "text/html":
            text = html_to_text(text)
    att = [f"{p.get_filename() or '(no name)'} ({p.get_content_type()}, {len(p.get_payload(decode=True) or b'')} bytes)"
           for p in _attachments(msg)]
    if att:
        lines.append("Attachments: " + "; ".join(att))
    text = text.strip()
    if len(text) > MAX_BODY:
        text = text[:MAX_BODY] + f"\n… ({len(text) - MAX_BODY} more characters)"
    return "\n".join(lines) + "\n\n" + text


TEXT_EXT = (".txt", ".csv", ".md", ".json", ".html", ".htm", ".xml", ".ics", ".eml", ".log", ".tsv", ".yaml", ".yml")


def get_attachment(m, a: dict) -> str:
    _select(m, a.get("folder"))
    msg = _fetch(m, a["uid"])
    want = str(a.get("name") or "").strip().lower()
    part = next((p for p in _attachments(msg) if (p.get_filename() or "").lower() == want), None)
    if part is None:
        names = ", ".join(p.get_filename() or "(no name)" for p in _attachments(msg)) or "none"
        return f"Error: no attachment {a.get('name')!r}; this message has: {names}"
    data = part.get_payload(decode=True) or b""
    if not (part.get_content_maintype() == "text" or want.endswith(TEXT_EXT)):
        return f"{part.get_filename()}: {part.get_content_type()}, {len(data)} bytes; not text, so not shown."
    text = data.decode(part.get_content_charset() or "utf-8", errors="replace")
    if want.endswith((".html", ".htm")):
        text = html_to_text(text)
    return text[:MAX_BODY] + (f"\n… ({len(text) - MAX_BODY} more characters)" if len(text) > MAX_BODY else "")


def list_folders(m, a: dict) -> str:
    typ, data = m.list()
    names = []
    for d in data or []:
        line = d.decode("utf-8", "replace") if isinstance(d, bytes) else str(d)
        mm = re.match(r'\((?P<flags>[^)]*)\) (?:"[^"]*"|NIL) (?P<name>.+)$', line)
        if mm and "\\Noselect" not in mm.group("flags"):
            n = mm.group("name").strip()
            if n.startswith('"') and n.endswith('"'):
                n = n[1:-1].replace('\\"', '"').replace("\\\\", "\\")
            names.append(_unutf7(n))
    return "Folders: " + ", ".join(names)


def _addrs(v) -> list[str]:
    items = v if isinstance(v, list) else [v] if v else []
    return [addr for _, addr in email.utils.getaddresses([str(x) for x in items]) if addr]


def compose(s: dict, a: dict, original=None) -> EmailMessage:
    sender = str(a.get("from_address") or s["user"]).strip()
    msg = EmailMessage()
    msg["From"] = sender
    for key, h in (("to", "To"), ("cc", "Cc")):
        if _addrs(a.get(key)):
            msg[h] = ", ".join(_addrs(a.get(key)))
    subject = str(a.get("subject") or "").strip()
    html = _html_of(a)
    if not subject and html:
        t = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
        subject = html_to_text(t.group(1)).strip() if t else ""
    if original is not None:
        if not subject:
            subject = _header(original, "Subject")
        if not re.match(r"(re|aw|odg):", subject, re.I):
            subject = "Re: " + subject
        mid = _header(original, "Message-ID")
        if mid:
            msg["In-Reply-To"] = mid
            msg["References"] = (_header(original, "References") + " " + mid).strip()
    msg["Subject"] = subject
    msg["Date"] = email.utils.formatdate(localtime=True)
    msg["Message-ID"] = email.utils.make_msgid(domain=sender.rpartition("@")[2] or None)
    body = str(a.get("body") or "").rstrip() or (html_to_text(html) if html else "")
    if not body and not html:
        raise ProtonError("the email is empty: give `body`, `html` or `html_file`")
    try:
        sig = s["signature"].read_text(encoding="utf-8").strip()
    except OSError:
        sig = ""
    if sig and sig not in body:
        body += "\n\n" + sig
    msg.set_content(body + "\n")
    if html:
        if sig and sig not in html_to_text(html):
            sig_html = "<br>".join(_esc(l) for l in sig.splitlines())
            html += f'\n<p style="color:#666;font-size:90%">{sig_html}</p>'
        if not re.search(r"<html", html, re.I):
            html = f'<!doctype html><html><head><meta charset="utf-8"></head><body>{html}</body></html>'
        if re.search(r"<table(?![^>]*(border|style))", html, re.I) and "<style" not in html.lower():
            # a bare <table> shows without any lines in mail clients: give it a plain grid
            css = ('<style>table{border-collapse:collapse}th,td{border:1px solid #bbb;padding:3px 8px;'
                   'text-align:left}th{background:#f2f2f2}</style>')
            html = re.sub(r"</head>", css + "</head>", html, count=1, flags=re.I) if re.search(
                r"</head>", html, re.I) else css + html
        msg.add_alternative(html, subtype="html")
    return msg


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _html_of(a: dict) -> str:
    """`html`, or the workspace file `html_file` (so a long HTML body is not retyped into the call)."""
    if a.get("html"):
        return str(a["html"])
    name = str(a.get("html_file") or "").strip()
    if not name:
        return ""
    f = Path(os.path.expanduser(name))
    if not f.is_absolute():
        try:
            import dl_mcp
            ws = dl_mcp.call_context().get("workspace")
        except ImportError:
            ws = None
        f = Path(ws or os.getcwd()) / f
    f = f.resolve()
    if not f.is_file():
        raise ProtonError(f"html_file {name!r} not found ({f})")
    try:
        import dl_mcp
        why = dl_mcp.file_leak(f)
        if why:
            raise ProtonError(f"BLOCKED: {why}")
    except ImportError:
        pass
    return f.read_text(encoding="utf-8", errors="replace")


def _original(s: dict, a: dict):
    if not a.get("reply_to_uid"):
        return None
    m = imap_connect(s)
    try:
        _select(m, a.get("folder"))
        return _fetch(m, a["reply_to_uid"])
    finally:
        _logout(m)


def draft_mail(m, a: dict, s: dict) -> str:
    original = None
    if a.get("reply_to_uid"):
        _select(m, a.get("folder"))
        original = _fetch(m, a["reply_to_uid"])
    msg = compose(s, a, original)
    if _addrs(a.get("bcc")):
        msg["Bcc"] = ", ".join(_addrs(a.get("bcc")))
    typ, data = m.append(_mailbox("Drafts"), "(\\Draft \\Seen)", imaplib.Time2Internaldate(time.time()),
                         msg.as_bytes(policy=email.policy.SMTP))
    if typ != "OK":
        raise ProtonError(f"saving the draft failed: {data}")
    return f"Draft saved in Drafts from {msg['From']}: {msg['Subject']}"


def update_mail(m, a: dict) -> str:
    uids = [int(u) for u in a.get("uids") or []]
    if not uids:
        return "Error: no uids given"
    target = str(a.get("move_to") or "").strip()
    if target and target.lower().rsplit("/", 1)[-1] in NO_MOVE:
        return "Error: moving mail to Trash or Spam is not allowed (no deleting); move it to another folder instead"
    _select(m, a.get("folder"), readonly=False)
    seq = ",".join(map(str, uids))
    done = []
    for key, flag in (("read", "\\Seen"), ("starred", "\\Flagged")):
        if isinstance(a.get(key), bool):
            typ, data = m.uid("STORE", seq, "+FLAGS" if a[key] else "-FLAGS", f"({flag})")
            if typ != "OK":
                raise ProtonError(f"changing {key} failed: {data}")
            done.append(f"{key}={a[key]}")
    if target:
        typ, data = m.uid("MOVE", seq, _mailbox(target))
        if typ != "OK":
            raise ProtonError(f"moving to {target!r} failed: {data}")
        done.append(f"moved to {target}")
    if not done:
        return "Error: nothing to change (give move_to, read or starred)"
    return f"{len(uids)} message(s): " + ", ".join(done)


def send_mail(a: dict, s: dict) -> str:
    to, cc, bcc = _addrs(a.get("to")), _addrs(a.get("cc")), _addrs(a.get("bcc"))
    if not to:
        return "Error: no recipient address in `to`"
    msg = compose(s, a, _original(s, a))
    smtp = smtp_connect(s)
    try:
        refused = smtp.send_message(msg, from_addr=msg["From"], to_addrs=to + cc + bcc)
    except smtplib.SMTPException as e:
        raise ProtonError(f"Bridge did not send it: {e}") from None
    finally:
        try:
            smtp.quit()
        except Exception:  # noqa: BLE001
            pass
    if refused:
        return f"Error: sent, but refused for: {', '.join(refused)}"
    return f"Sent from {msg['From']} to {', '.join(to + cc + bcc)}: {msg['Subject']}"


def _logout(m) -> None:
    try:
        m.logout()
    except Exception:  # noqa: BLE001
        pass


def call(tool: str, args: dict) -> str:
    """The built-in's handler: one tool call, one Bridge connection."""
    a = dict(args or {})
    try:
        s = settings()
        if tool == "send_mail":
            return send_mail(a, s)
        fn = {"search_mail": search_mail, "read_mail": read_mail, "get_attachment": get_attachment,
              "list_folders": list_folders, "update_mail": update_mail}.get(tool)
        if fn is None and tool != "draft_mail":
            return f"Error: unknown tool {tool!r}"
        m = imap_connect(s)
        try:
            return draft_mail(m, a, s) if tool == "draft_mail" else fn(m, a)
        finally:
            _logout(m)
    except ProtonError as e:
        return f"Error: {e}"
    except (OSError, imaplib.IMAP4.error, smtplib.SMTPException) as e:
        return f"Error: Proton Mail Bridge: {type(e).__name__}: {e}"


if __name__ == "__main__":  # quick check: python tools/dl_proton.py  -> the folder list
    print(call("list_folders", {}))
