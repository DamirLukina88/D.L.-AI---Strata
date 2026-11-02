"""tools/dl_translate.py - DeepL for D.L. CLI: whole texts, HTML and files, standard library only.

Registered as the built-in "deepl" (mcp.json {"builtin": "deepl"}); it replaces the deepl-mcp-server, which could
only translate separate strings.  DeepL translates each text with the context inside it, so a finished email or
table goes in as ONE text (HTML keeps the table and its tags) - never word by word.  The result is used exactly as
returned: the local model does not know Croatian or German well enough to "correct" it.

Key: DEEPL_API_KEY (environment or ~/.config/dl-ai/secrets.env); a key ending in ":fx" uses the free API.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

SECRETS_ENV = Path.home() / ".config" / "dl-ai" / "secrets.env"
TIMEOUT = 60
MAX_CHARS = 120_000                  # DeepL takes 128 KiB per request

TOOLS = [
    {"name": "translate", "description": (
        "Translate with DeepL. Give the WHOLE finished text in one call (an email, a document, a table as HTML), "
        "never single words or fragments: DeepL needs the context. Use the result exactly as returned; never edit "
        "or re-translate it. With `file` and `out_file` the text is read from and written to workspace files, so "
        "you need not retype it (e.g. translate email_en.html to email_hr.html, then send it with html_file). For an email "
        "put the subject in the HTML <title> so it is translated with the text, and leave send_mail's subject out."),
     "inputSchema": {"type": "object", "properties": {
         "text": {"type": "string", "description": "The text to translate (or give `file`)"},
         "file": {"type": "string", "description": "A workspace file to translate instead of `text`"},
         "out_file": {"type": "string", "description": "Write the translation to this workspace file"},
         "target_lang": {"type": "string", "description": "HR, DE, EN-GB, EN-US, FR, IT, ..."},
         "source_lang": {"type": "string", "description": "Optional; DeepL detects it"},
         "html": {"type": "boolean", "description": "The text is HTML: tags and tables are kept"},
         "context": {"type": "string", "description": "What the text is about (not translated, helps the wording)"},
         "formality": {"type": "string", "enum": ["default", "more", "less", "prefer_more", "prefer_less"]}},
         "required": ["target_lang"]}},
]


class TranslateError(Exception):
    pass


def _key() -> str:
    k = os.environ.get("DEEPL_API_KEY", "")
    if not k:
        try:
            for line in SECRETS_ENV.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip().removeprefix("export ").strip()
                if line.startswith("DEEPL_API_KEY="):
                    k = line.partition("=")[2].strip().strip("'\"")
        except OSError:
            pass
    if not k:
        raise TranslateError("DEEPL_API_KEY is missing from ~/.config/dl-ai/secrets.env")
    return k


def _post(path: str, body: dict) -> dict:
    key = _key()
    host = "api-free.deepl.com" if key.endswith(":fx") else "api.deepl.com"
    req = urllib.request.Request(f"https://{host}/v2/{path}", data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Authorization": f"DeepL-Auth-Key {key}",
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        msg = e.read().decode("utf-8", "replace")[:300]
        if e.code == 456:
            raise TranslateError("the DeepL quota for this month is used up") from None
        raise TranslateError(f"DeepL HTTP {e.code}: {msg}") from None
    except (urllib.error.URLError, OSError) as e:
        raise TranslateError(f"DeepL is not reachable: {e}") from None


def translate(text: str, target: str, source: str = "", html: bool = False, context: str = "",
              formality: str = "") -> tuple[str, str]:
    """-> (translation, detected source language)."""
    if not text.strip():
        raise TranslateError("nothing to translate")
    if len(text) > MAX_CHARS:
        raise TranslateError(f"the text has {len(text):,} characters; DeepL takes about {MAX_CHARS:,} per call")
    body = {"text": [text], "target_lang": target.strip().upper()}
    if source:
        body["source_lang"] = source.strip().upper().split("-")[0]
    if html:
        body["tag_handling"] = "html"
    if context:
        body["context"] = context
    if formality and formality != "default":
        body["formality"] = formality
    out = _post("translate", body).get("translations") or [{}]
    return str(out[0].get("text") or ""), str(out[0].get("detected_source_language") or "")


def detect(text: str) -> str:
    """The language of a text (DeepL's detection), e.g. 'HR', 'EN'; '' when unknown."""
    try:
        return translate(text[:300], "EN-GB")[1]
    except TranslateError:
        return ""


RECORDED_DEEPL_HASHES: set[str] = set()


def record_translation_output(text: str, file_path: Path | str | None = None) -> None:
    """Record that text or a file was generated by DeepL, so send_mail allows it."""
    if text:
        h = hashlib.sha256(text.encode("utf-8")).hexdigest()
        RECORDED_DEEPL_HASHES.add(h)
        h_norm = hashlib.sha256(re.sub(r"\s+", " ", text).strip().encode("utf-8")).hexdigest()
        RECORDED_DEEPL_HASHES.add(h_norm)
    if file_path:
        p = Path(file_path).resolve()
        RECORDED_DEEPL_HASHES.add(str(p))
        if p.is_file():
            try:
                c = p.read_text(encoding="utf-8", errors="replace")
                RECORDED_DEEPL_HASHES.add(hashlib.sha256(c.encode("utf-8")).hexdigest())
                RECORDED_DEEPL_HASHES.add(hashlib.sha256(re.sub(r"\s+", " ", c).strip().encode("utf-8")).hexdigest())
            except OSError:
                pass


def is_recorded_translation(text: str, file_path: Path | str | None = None) -> bool:
    """True when text or file matches an output produced by DeepL in this session."""
    if file_path:
        p = Path(file_path).resolve()
        if str(p) in RECORDED_DEEPL_HASHES:
            return True
        if p.is_file():
            try:
                c = p.read_text(encoding="utf-8", errors="replace")
                if hashlib.sha256(c.encode("utf-8")).hexdigest() in RECORDED_DEEPL_HASHES:
                    return True
                if hashlib.sha256(re.sub(r"\s+", " ", c).strip().encode("utf-8")).hexdigest() in RECORDED_DEEPL_HASHES:
                    return True
            except OSError:
                pass
    if text:
        if hashlib.sha256(text.encode("utf-8")).hexdigest() in RECORDED_DEEPL_HASHES:
            return True
        if hashlib.sha256(re.sub(r"\s+", " ", text).strip().encode("utf-8")).hexdigest() in RECORDED_DEEPL_HASHES:
            return True
    return False


def check_email_language(body: str = "", html: str = "", html_file: str | Path | None = None) -> str | None:
    """Check if outgoing email is English or was translated by DeepL.
    Returns None if allowed to send, or an error message string if blocked.
    """
    raw_content = ""
    resolved_file = None
    if html_file:
        try:
            import dl_mcp
            ws = dl_mcp.call_context().get("workspace")
        except ImportError:
            ws = None
        f = Path(os.path.expanduser(str(html_file)))
        if not f.is_absolute():
            f = Path(ws or os.getcwd()) / f
        resolved_file = f.resolve()
        if resolved_file.is_file():
            try:
                raw_content = resolved_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                pass
    if not raw_content:
        raw_content = html or body
    if not raw_content.strip():
        return None

    # If it was produced by DeepL in this session, sending is allowed regardless of language
    if is_recorded_translation(raw_content, resolved_file):
        return None

    # Extract text sample for DeepL language detection (strip HTML tags if present)
    if html or html_file or "<html" in raw_content.lower() or "<body" in raw_content.lower():
        text_sample = re.sub(r"<[^>]+>", " ", raw_content)
        text_sample = re.sub(r"\s+", " ", text_sample).strip()
    else:
        text_sample = raw_content.strip()

    if not text_sample:
        return None

    # Detect language via DeepL
    try:
        _, detected = translate(text_sample[:400], "EN-GB")
    except TranslateError as e:
        return f"Error: could not verify email language (DeepL is not reachable: {e}). Email was not sent."
    except Exception as e:
        return f"Error: could not verify email language ({e}). Email was not sent."

    detected_code = (detected or "").upper()
    if detected_code.startswith("EN"):
        return None

    return (
        f"Error: This email is in {detected_code} but was not translated by DeepL. "
        "Write it in English, turn on deepl (`mcp(action=\"enable\", server=\"deepl\")`), "
        "translate it and send the out_file."
    )


def _workspace_path(name: str, must_exist: bool) -> Path:
    try:
        import dl_mcp
        ws = Path(dl_mcp.call_context().get("workspace") or os.getcwd())
    except ImportError:
        ws = Path(os.getcwd())
    f = Path(os.path.expanduser(name))
    f = (f if f.is_absolute() else ws / f).resolve()
    if not f.is_relative_to(ws.resolve()):
        raise TranslateError(f"{name!r} is outside the workspace {ws}")
    if must_exist and not f.is_file():
        raise TranslateError(f"{name!r} not found ({f})")
    if must_exist:
        try:
            import dl_mcp
            why = dl_mcp.file_leak(f)
            if why:
                raise TranslateError(f"BLOCKED: {why}")
        except ImportError:
            pass
    return f


def call(tool: str, args: dict) -> str:
    a = dict(args or {})
    if tool != "translate":
        return f"Error: unknown tool {tool!r}"
    try:
        src_file = _workspace_path(str(a["file"]), True) if a.get("file") else None
        dest = _workspace_path(str(a["out_file"]), False) if a.get("out_file") else None    # checked before DeepL
        text = src_file.read_text(encoding="utf-8", errors="replace") if src_file else str(a.get("text") or "")
        flag = a.get("html")                             # "false" is no: bool("false") would be True
        flag = flag is True or (type(flag) is int and flag == 1) or (
            isinstance(flag, str) and flag.strip().lower() in ("true", "yes", "1"))
        html = flag or bool(src_file and src_file.suffix.lower() in (".html", ".htm"))
        out, detected = translate(text, str(a.get("target_lang") or ""), str(a.get("source_lang") or ""), html,
                                  str(a.get("context") or ""), str(a.get("formality") or ""))
        note = f"DeepL {detected or '?'} -> {str(a.get('target_lang')).upper()}"
        if dest:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(out, encoding="utf-8")
            record_translation_output(out, dest)
            return (f"{note}: wrote {len(out):,} characters to {dest}. Use that file as it is (e.g. html_file); do "
                    f"not edit it.\n\nStart:\n{out[:600]}")
        record_translation_output(out)
        return f"{note} (use exactly as is, do not edit):\n{out}"
    except TranslateError as e:
        return f"Error: {e}"
    except (OSError, ValueError) as e:
        return f"Error: {type(e).__name__}: {e}"
