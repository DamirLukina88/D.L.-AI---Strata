"""Ray's phone bridge, download tickets and the workspace path guard.

Moved out of serve/server.py without changes; see server.py for the entry point and the names tests patch."""
from __future__ import annotations

from pathlib import Path
from pathlib import PurePosixPath
import secrets
import threading
import time
from serve.late import server as _server


class PhoneBridge:
    def __init__(self):
        self.lock = threading.Lock()
        self.pending_calls: dict[str, dict] = {}
        self.last_seen = 0.0
        self.is_connected = False
        self.sensor_stream: dict = {}
        self.clipboard: dict = {"text": "", "hash": "", "source": "", "updated_ms": 0}

    def report_heartbeat(self):
        with self.lock:
            self.last_seen = time.time()
            self.is_connected = True

    def get_status(self) -> dict:
        with self.lock:
            active = (time.time() - self.last_seen) < 30.0
            return {"connected": active, "last_seen": self.last_seen, "pending_count": len(self.pending_calls)}

    def enqueue_call(self, tool: str, args: dict, timeout: float = 6.0) -> str | None:
        with self.lock:
            active = (time.time() - self.last_seen) < 30.0
            if not active:
                return None
            call_id = f"phone_{int(time.time() * 1000)}_{secrets.token_hex(2)}"
            ev = threading.Event()
            entry = {"id": call_id, "tool": tool, "args": args, "created": time.time(), "event": ev, "result": None, "dispatched": False}
            self.pending_calls[call_id] = entry
        finished = ev.wait(timeout)
        with self.lock:
            res_entry = self.pending_calls.pop(call_id, None)
        if not finished or not res_entry or res_entry.get("result") is None:
            return None
        return res_entry["result"]

    def pop_pending_call(self) -> dict | None:
        with self.lock:
            now = time.time()
            for cid, entry in list(self.pending_calls.items()):
                if entry.get("dispatched"):
                    continue                 # the phone is running it (a photo can take over 10 s); enqueue_call ends it
                if now - entry["created"] > 10.0:
                    self.pending_calls.pop(cid, None)
                    continue
                entry["dispatched"] = True
                return {"id": entry["id"], "tool": entry["tool"], "args": entry["args"]}
        return None

    def post_result(self, call_id: str, result: str) -> bool:
        with self.lock:
            self.last_seen = time.time()
            self.is_connected = True
            entry = self.pending_calls.get(call_id)
            if entry:
                entry["result"] = result
                entry["event"].set()
                return True
        return False


PHONE_BRIDGE = PhoneBridge()


# The app's own way in, for the voice drawer (com.damirl.ray PhoneToolRelay).  Cloudflare Access answers /api/* itself
# unless the caller has its login cookie, which only the web page has; /v1/* passes it and needs the API key.  So on the
# road, with the phone locked, the app can reach these and not /api/phone/* or /api/workspace/upload
PHONE_PENDING_PATH = "/v1/ray/phone/pending"


PHONE_RESULT_PATH = "/v1/ray/phone/result"


PHONE_UPLOAD_PATH = "/v1/ray/phone/upload"


PHONE_DOWNLOAD_PATH = "/v1/ray/phone/download"


PHONE_SENSORS_STREAM_PATH = "/v1/ray/phone/sensors/stream"


PHONE_CLIPBOARD_PATH = "/v1/ray/phone/clipboard"


def is_phone_photo(name: str) -> bool:
    """A path under phone-photos/ or phone-files/: all the phone companion app's upload may write."""
    parts = PurePosixPath(name or "").parts
    return len(parts) >= 2 and parts[0] in ("phone-photos", "phone-files") and ".." not in parts


_download_tickets: dict[str, tuple[Path, float]] = {}


_download_tickets_lock = threading.Lock()


def new_download_ticket(target: Path, ttl: float = 60.0) -> str:
    """A single-use, short-lived name for one workspace file, so a browser can download it by plain navigation
    without the API key in the URL (the LAN case; behind Cloudflare Access the login cookie does it)."""
    tok = secrets.token_urlsafe(24)
    now = time.monotonic()
    with _download_tickets_lock:
        for k in [k for k, (_, exp) in _download_tickets.items() if exp < now]:
            del _download_tickets[k]
        _download_tickets[tok] = (target, now + ttl)
    return tok


def take_download_ticket(tok: str) -> Path | None:
    with _download_tickets_lock:
        target, exp = _download_tickets.pop(tok, (None, 0.0))
    return target if target is not None and exp >= time.monotonic() else None


def safe_workspace_path(rel_path: str) -> Path | None:
    if not rel_path:
        return None
    try:
        clean = rel_path.lstrip("/\\")
        target = (_server().WORKSPACE_DIR / clean).resolve()
        target.relative_to(_server().WORKSPACE_DIR)
        if target == _server().WORKSPACE_DIR:
            return None
        return target
    except (ValueError, Exception):
        return None
