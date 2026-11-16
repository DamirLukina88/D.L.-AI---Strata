"""The vision encoder process (strata-vision) and image fetching.

Moved out of serve/server.py without changes; see server.py for the entry point and the names tests patch."""
from __future__ import annotations

from http.client import HTTPException
from pathlib import Path
import base64
import hashlib
import os
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.request
from serve.late import server as _server
from serve.engine import engine_exit_words
from serve.errors import ClientGone


IMAGE_URL_MAX = 32 << 20        # an image URL is read up to this (the web app attaches pictures of up to 20 MB)


def network_path(path: str) -> bool:
    r"""A path to another computer: \\host\share or //host/share (either slash), \\?\UNC\host\..., \\.\UNC\host\...
    or the NT form \??\UNC\host\...  Windows connects to that host at the first look at the path (os.path.isfile is
    enough) and signs in with the user's NTLM credentials.  \\?\ and \??\ name local files too; no client needs them."""
    p = path.replace("/", "\\")
    return p.startswith("\\\\") or p.startswith("\\??\\")


def vision_log_tail(log=None, limit: int = 16384) -> str:
    """The last `limit` bytes of the encoder's stderr file (`log` is the file object it was started with; "" when there
    is none or it cannot be read)."""
    try:
        name = getattr(log, "name", None)
        if name:
            with open(name, "rb") as f:
                f.seek(0, 2)
                f.seek(max(0, f.tell() - limit))
                return f.read().decode("utf-8", "replace")
    except (OSError, ValueError):
        pass
    return ""


# What the CUDA / HIP runtimes print when the reader has no code for the card it runs on (a binary built without that
# architecture: #3669, the Windows cuda12 package's reader on a Pascal card).
_VISION_ARCH_SIGNS = ("device kernel image is invalid", "no kernel image is available", "im2col failed",
                      "unsupported gpu architecture", "invalid device function", "unknown gpu architecture")


def vision_start_error(line: str, log=None, code: int | None = None, waited: float | None = None, strays=()) -> str:
    """The message when the image encoder answered something other than READY.  #1445: a card in the Exclusive_Process
    compute mode (or one another process holds) refuses the encoder's CUDA context with "busy or unavailable"; that
    cause is named instead of leaving the user the first line of a traceback.  `log` is the encoder's stderr file, whose
    tail is searched too (the CUDA error is printed there).  An encoder that dies before it prints anything (#3645, #3444,
    #3669, #3697) used to give a blank sentence: now the last lines of its stderr, its exit status (`code`) and, for a
    kernel-image error, the card/architecture hint come with it.  `waited`: it said nothing for that many seconds.  `strays`: lines it printed on
    its output before it ended that were not an answer (a debugger's, a library's); they are searched for the causes below and named in the message."""
    text = line.strip()
    tail = vision_log_tail(log)
    both = (text + chr(10) + chr(10).join(strays) + chr(10) + tail).lower()
    if "busy or unavailable" in both:
        return ("the vision encoder did not start: the GPU refused a second CUDA context (\"CUDA-capable device(s) "
                "is/are busy or unavailable\"). This is usually the compute mode Exclusive_Process: only one process "
                "may use the card, and the engine already holds it. Check with: nvidia-smi --query-gpu=compute_mode "
                "--format=csv; set it back with: sudo nvidia-smi -c DEFAULT (or run the encoder on another card). "
                "First line from the encoder: " + (text or "(none)"))
    lines = [x.strip() for x in tail.splitlines() if x.strip()]
    if any(sign in both for sign in _VISION_ARCH_SIGNS):
        evidence = next((x for x in reversed(lines) if any(sign in x.lower() for sign in _VISION_ARCH_SIGNS)), text)
        return ("the vision encoder did not start: it has no code for this graphics card (a kernel-image error: the "
                "picture reader in this engine package was built for other card generations than yours). Update the "
                "engine, or read pictures on the CPU (Models, Read pictures, Image encoder device: CPU; or run setup "
                "again with --vision cpu). From the encoder: " + evidence[:300])
    if text:
        msg = "the vision encoder did not start: " + text
    elif waited is not None:
        msg = f"the vision encoder did not start: it said nothing for {waited:g} s (it never reported READY)"
    else:
        msg = "the vision encoder did not start: it ended without saying anything"
    extra = []
    if code is not None:
        words = engine_exit_words(code)
        if words:
            extra.append(words)
    if strays:
        extra.append("it also printed on its output: " + " | ".join(x[:120] for x in list(strays)[-3:]))
    shown = [x for x in lines[-3:] if x != text]
    if shown:
        extra.append("last lines of its log: " + " | ".join(x[:200] for x in shown))
    if extra:
        msg += " (" + "; ".join(extra) + ")"
    return msg


class Vision:
    """The resident image encoder: `strata-vision` (llama.cpp mtmd + the mmproj file) reads `ENC <image> <out>`
    lines and writes each image's embeddings; results are cached by the image's hash, so a conversation that
    sends the same picture again (every turn, with most clients) encodes it once."""

    @staticmethod
    def work_dir() -> Path:
        """#480: the directory for the encoder's files.  The engine reads the embeddings file named in a `GENI` line
        and the encoder the output named in an `ENC <image> <out>` line, both split at spaces, so a space in the path
        (a %TEMP% under a user name with a space) broke every image.  The system temp directory is used while its path
        has no space, then the working directory, then the system drive's root; the plain temp directory is the last
        resort (the encoder's own files are then named relative to it, see `_start`)."""
        for parent in (None, Path.cwd(), Path(os.environ.get("SystemDrive", "C:") + os.sep)):
            try:
                d = Path(tempfile.mkdtemp(prefix="strata-vision-", dir=parent))
            except OSError:
                continue                                       # not writable, or no such drive
            if " " not in str(d):
                return d
            try:
                d.rmdir()                                      # just created, so still empty
            except OSError:
                pass
        return Path(tempfile.mkdtemp(prefix="strata-vision-"))

    def __init__(self, cfg: dict, log=None, env: dict | None = None, lazy: bool = False):
        args = self.reader_args(cfg)
        self.dir = self.work_dir()
        self.spawn = (args, log, env)                   # to start it again after an unload
        self.proc = None
        self.stopped = True
        self.lock = threading.Lock()
        self.cache: dict[str, tuple[Path, int]] = {}
        # opt-in (the vision section's "elastic": true, with the config's "vram_elastic"): the encoder starts with the
        # first picture and stops after elastic_idle_s without one; while it runs, the engine's expert cache keeps
        # elastic_mib of VRAM free for it (Service._vision_up / _vision_idle_down)
        self.max_tokens = self.token_limit(cfg)
        # a camera photo larger than this (long side, px) is scaled down before it is read (0 = never); screenshots
        # and small pictures go through as they are (shrink())
        self.max_side = int(cfg["max_side"]) if cfg.get("max_side") is not None else 1568
        self.elastic = cfg.get("elastic") is True
        self.elastic_mib = int(cfg["elastic_mib"]) if cfg.get("elastic_mib") is not None else 2048
        self.elastic_idle_s = float(cfg.get("elastic_idle_s") or 120)
        if not lazy and not self.elastic:
            self._start()

    # What a picture may become when the config does not say (setup writes the same numbers, setup.VISION): an old, hand-edited or migrated
    # config without vision.max_tokens left the reader unclamped, and #3690 saw one picture become 93,700 image tokens (I7).  A key that is
    # there is the person's: 0 means no limit, as before.
    DEFAULT_MAX_TOKENS = {"gpu": 1024, "cpu": 300}

    @staticmethod
    def token_limit(cfg: dict) -> int:
        """The --max-tokens of a reader config: its max_tokens, else the default of its kind (GPU 1024, CPU 300)."""
        if cfg.get("max_tokens") is not None:
            try:
                return max(0, int(cfg["max_tokens"]))
            except (TypeError, ValueError):
                pass
        return Vision.DEFAULT_MAX_TOKENS["gpu" if cfg.get("gpu") else "cpu"]

    @staticmethod
    def reader_args(cfg: dict) -> list:
        absolute = lambda p: os.path.abspath(p) if os.path.dirname(str(p)) else p   # the encoder runs in its own dir (#480)  # noqa: E731
        args = [absolute(cfg["exe"]), "--mmproj", absolute(cfg["mmproj"]), "--model", absolute(cfg["model"])]
        if cfg.get("gpu"):
            args.append("--gpu")
        if cfg.get("threads"):
            args += ["--threads", str(cfg["threads"])]
        limit = Vision.token_limit(cfg)
        if limit:
            args += ["--max-tokens", str(limit)]
        if cfg.get("min_tokens"):                       # #767: mtmd's image_min_tokens (a hand-edited key)
            args += ["--min-tokens", str(cfg["min_tokens"])]
        return args

    def _start(self):
        args, log, env = self.spawn
        # cwd is the encoder's directory: the ENC lines name the files relative to it (#480: no space in the line)
        self.proc = _server().popen("the image encoder", args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                          stderr=log or subprocess.DEVNULL, text=True, encoding="utf-8", bufsize=1, env=env,
                          cwd=self.dir)
        _server().contain(self.proc)
        strays: list[str] = []
        try:
            line = self._await_ready(_server().VISION_READY_S, strays)
        except RuntimeError as e:                       # silent for VISION_READY_S: it was ended, and it is not left half-started
            self.proc, self.stopped = None, True
            if _server().VISION_READY_S:
                raise RuntimeError(vision_start_error("", log, waited=_server().VISION_READY_S, strays=strays)) from None
            raise RuntimeError(str(e)) from None
        if not line.startswith("READY"):
            proc, self.proc = self.proc, None
            self.stopped = True
            code = proc.poll() if hasattr(proc, "poll") else None   # an encoder that died by itself has its status already
            try:
                proc.kill()
                proc.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                pass
            if code is None:
                code = getattr(proc, "returncode", None)
            raise RuntimeError(vision_start_error(line, log, code, strays=strays))
        self.stopped = False

    #: how long a reader that has already ended may still hold its output pipe open (a debugger attached to it, a child it started) before the start is
    #: judged: the pipe's end does not come, the process's end is what counts.
    READY_GRACE_S = 2.0
    #: lines kept from a reader's output before its answer (and written to the log): enough to see what it said, not a flood
    STRAY_KEEP = 20

    def _await_ready(self, timeout: float | None, strays: list) -> str:
        """The reader's answer to its start: "READY ..." or "ERR ..." (what strata-vision prints on stdout; everything else it says goes to stderr),
        or "" when it has ended.  Any other line on stdout is a stray line - a debugger a crashing reader started, a library's banner - and is not an
        answer: it is kept in `strays` (the last STRAY_KEEP), written to the log, and the wait goes on.  A reader that is only printing is never killed.
        The wait has ONE deadline of `timeout` s (None: for ever); on it the reader is killed and the read raises RuntimeError, as `_readline` does.  A
        reader whose process has ended while a debugger or a child still holds its pipe open counts as ended after READY_GRACE_S.  The thread that
        reads stops at the answer, so the encode answers that follow are never taken by it."""
        proc = self.proc
        got: queue.Queue = queue.Queue()

        def read():
            while True:
                try:
                    line = proc.stdout.readline()
                except (OSError, ValueError):           # killed under the read
                    line = ""
                got.put(line)
                if not line or line.startswith(("READY", "ERR")):
                    return

        threading.Thread(target=read, daemon=True).start()
        deadline = None if timeout is None else time.monotonic() + timeout
        ended_at = None
        said = 0
        while True:
            now = time.monotonic()
            if deadline is not None and now >= deadline:
                try:
                    proc.kill()
                except OSError:
                    pass
                raise RuntimeError(f"the vision encoder did not start: it said nothing for {timeout:.0f} s")
            try:
                line = got.get(timeout=0.25 if deadline is None else max(0.01, min(0.25, deadline - now)))
            except queue.Empty:
                code = proc.poll() if hasattr(proc, "poll") else None
                if code is not None:
                    ended_at = now if ended_at is None else ended_at
                    if now - ended_at >= self.READY_GRACE_S:
                        return ""
                continue
            if not line or line.startswith(("READY", "ERR")):
                return line
            stray = line.strip()
            if stray:
                strays.append(stray[:300])
                del strays[:-self.STRAY_KEEP]
                said += 1
                if said <= self.STRAY_KEEP:
                    print(f"[strata] the image encoder printed on its output, not an answer: {stray[:200]}", flush=True)

    def _readline(self, timeout: float, what: str) -> str:
        """One line from the encoder, waiting at most `timeout` s (#1317).  On a timeout the encoder is killed, so the
        next request starts a fresh one, and the read raises RuntimeError instead of holding the request turn."""
        proc = self.proc
        got: queue.Queue = queue.Queue()

        def read():
            try:
                got.put(proc.stdout.readline())
            except (OSError, ValueError):               # killed under the read
                got.put("")

        threading.Thread(target=read, daemon=True).start()
        try:
            return got.get(timeout=timeout)
        except queue.Empty:
            try:
                proc.kill()
            except OSError:
                pass
            raise RuntimeError(f"{what}: it said nothing for {timeout:.0f} s") from None

    def alive(self) -> bool:
        return self.proc is not None and not self.stopped and self.proc.poll() is None

    def unload(self):
        """Stop the encoder process (its VRAM or RAM goes back); the encoded images stay cached on disk."""
        self.close()
        self.stopped = True

    def restart(self):
        """Start the encoder again after an unload (or if it died); the cache of encoded images is kept."""
        if self.proc is not None:
            try:
                self.proc.kill()
            except OSError:
                pass
        self.proc = None
        self.stopped = True
        self._start()

    @staticmethod
    def load(source: str) -> bytes:
        if source.startswith("data:"):
            try:
                return base64.b64decode(source.split(",", 1)[1])
            except (IndexError, ValueError) as e:                # no comma, or not base64
                raise ValueError(f"the image's data: URL could not be read ({e})") from None
        if source.startswith(("http://", "https://")):
            return Vision.download(source)
        path = source[7:] if source.startswith("file://") else source
        # refused before anything looks at the path: file://host/share/x.png is \\host\share\x.png ("file://C:/x.png",
        # a drive, is a client's spelling of file:///C:/x.png)
        host = re.split(r"[/\\]", path, maxsplit=1)[0] if source.startswith("file://") else ""
        if network_path(path) or host and not re.fullmatch(r"[A-Za-z]:|localhost", host, re.IGNORECASE):
            raise ValueError("an image file must be on this computer: network paths (\\\\host\\share, //host/share, "
                             "file://host/...) are not read")
        if path and os.path.isfile(path):
            try:
                return Path(path).read_bytes()
            except OSError as e:
                raise ValueError(f"the image could not be read from {path} ({e})") from None
        raise ValueError("an image must be a data: URL, an http(s) URL or a local file path")

    @staticmethod
    def download(url: str) -> bytes:
        """An image URL's bytes, at most IMAGE_URL_MAX of them: the whole response was read, so a huge or endless one
        filled the memory.  One that cannot be read is a ValueError (a 400 that says so), not a dropped connection."""
        too_big = f"the image URL's file is over {_server().IMAGE_URL_MAX >> 20} MiB"
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "strata"}), timeout=60) as r:
                size = r.headers.get("Content-Length") or ""
                if size.isdigit() and int(size) > _server().IMAGE_URL_MAX:
                    raise ValueError(too_big)
                data = r.read(_server().IMAGE_URL_MAX + 1)
        except (OSError, HTTPException) as e:
            raise ValueError(f"the image URL could not be read: {e}") from None
        if len(data) > _server().IMAGE_URL_MAX:
            raise ValueError(too_big)
        return data

    @staticmethod
    def _exif_rotated(data: bytes) -> bool:
        """A JPEG whose EXIF Orientation says it is stored turned (phones do this for portrait photos): the decoder
        (stb_image) ignores the tag.  False without Pillow, or when the tag is missing, 1 or unreadable (#1229)."""
        try:
            import io
            from PIL import Image
            with Image.open(io.BytesIO(data)) as im:
                return im.getexif().get(0x0112, 1) not in (None, 0, 1)
        except Exception:  # noqa: BLE001 - any failure leaves the image as it was sent
            return False

    CAMERA_SIDE = 3000                  # a picture this large (long side) is a camera photo, EXIF or not

    @staticmethod
    def shrink(data: bytes, max_side: int) -> bytes:
        """A camera photo (a JPEG with the camera's EXIF Make/Model, or any picture whose long side is CAMERA_SIDE or
        more) larger than max_side is scaled down to it and sent as a JPEG (quality 90): the reader resizes it anyway,
        and a 12-50 MP photo costs decode time and memory for nothing.  Screenshots and smaller pictures - where the
        detail is text - go through unchanged, as does everything without Pillow (2026-11-15, per picture)."""
        if not max_side or max_side <= 0:
            return data
        try:
            import io
            from PIL import Image
            with Image.open(io.BytesIO(data)) as im:
                long_side = max(im.size)
                if long_side <= max_side:
                    return data
                camera = False
                if im.format == "JPEG":
                    exif = im.getexif()
                    camera = bool(exif.get(0x010F) or exif.get(0x0110))      # Make, Model
                if not camera and long_side < Vision.CAMERA_SIDE:
                    return data
                im = im.convert("RGB")
                im.thumbnail((max_side, max_side), Image.LANCZOS)
                out = io.BytesIO()
                im.save(out, format="JPEG", quality=90)
                return out.getvalue()
        except Exception:  # noqa: BLE001 - any failure leaves the picture as it was
            return data

    @staticmethod
    def normalize(data: bytes) -> bytes:
        """The formats strata-vision's decoder (stb_image) reads pass through; anything else is converted to PNG.
        A JPEG with an EXIF Orientation other than 1 is turned upright first (needs Pillow)."""
        jpeg = data[:3] == b"\xff\xd8\xff"
        if (jpeg and not Vision._exif_rotated(data)) or data[:8] == b"\x89PNG\r\n\x1a\n" or data[:2] == b"BM" or \
                data[:6] in (b"GIF87a", b"GIF89a"):
            return data
        try:
            import io
            from PIL import Image
        except ImportError:
            raise ValueError("this image format needs Pillow (python -m pip install pillow); JPEG, PNG, BMP and "
                             "GIF work without it") from None
        try:
            im = Image.open(io.BytesIO(data))
            im.load()
            from PIL import ImageOps
            im = ImageOps.exif_transpose(im)             # the camera's orientation tag, applied (#1229)
        except Exception as e:
            raise ValueError(f"the image could not be read ({e})") from None
        if im.mode in ("RGBA", "LA", "P") and "transparency" in im.info or im.mode in ("RGBA", "LA"):
            im = im.convert("RGBA")
            bg = Image.new("RGB", im.size, (255, 255, 255))   # transparent areas become white, not black
            bg.paste(im, mask=im.split()[-1])
            im = bg
        elif im.mode != "RGB":
            im = im.convert("RGB")
        out = io.BytesIO()
        im.save(out, format="PNG")
        return out.getvalue()

    def encode_all(self, sources: list, cancel=None) -> list[tuple[Path, int]]:
        """encode() for every image of one request: the files of this request's earlier images are never evicted to
        make room for a later one (#1072: with more than 64 unique images the first was deleted before the request
        had read it).  `cancel` (#1999): a request whose client left does not encode its next pictures."""
        out: list[tuple[Path, int]] = []
        for src in sources:
            if cancel is not None and cancel.is_set():
                raise ClientGone()
            out.append(self.encode(src, keep=[p for p, _ in out]))
        return out

    def encode(self, source: str | bytes, keep=()) -> tuple[Path, int]:
        """-> (embeddings file, number of image tokens).  `source`: what load() reads, or the image's bytes.
        `keep`: files the caller still needs (never evicted by this call)."""
        data = self.shrink(self.normalize(source if isinstance(source, bytes) else self.load(source)),
                           getattr(self, "max_side", 1568))
        key = hashlib.sha256(data).hexdigest()[:32]
        with self.lock:
            if key in self.cache:
                self.cache[key] = self.cache.pop(key)                  # most recently used last
                return self.cache[key]
            if self.proc is None or self.proc.stdin is None:           # an elastic encoder not started yet, or one that was unloaded
                raise ValueError("the picture reader is not running")
            img, out = self.dir / f"{key}.img", self.dir / f"{key}.sve"
            img.write_bytes(data)
            try:
                self.proc.stdin.write(f"ENC {img.name} {out.name}\n")      # relative to the encoder's cwd (#480)
                self.proc.stdin.flush()
                try:
                    line = self._readline(_server().VISION_ENCODE_S, "the image could not be read").strip()
                except RuntimeError as e:                 # silent for VISION_ENCODE_S: the encoder was ended (#1317)
                    self.stopped = True                   # alive() is False, so the next request starts it again
                    raise ValueError(str(e)) from None
            finally:                                                   # #352: also when the encoder's pipe is gone
                img.unlink(missing_ok=True)
            if not line.startswith("OK"):
                raise ValueError("the image could not be read: " + (line[4:] if line.startswith("ERR") else
                                                                     "the vision encoder stopped"))
            self.cache[key] = (out, int(line.split()[1]))
            self.warn_if_over_limit(self.cache[key][1])
            held = {str(p) for p in keep} | {str(out)}
            for old in list(self.cache):                               # oldest first, but never one still in use
                if len(self.cache) <= 64:
                    break
                if str(self.cache[old][0]) not in held:
                    self.cache.pop(old)[0].unlink(missing_ok=True)
            return self.cache[key]

    def warn_if_over_limit(self, tokens: int) -> None:
        """I7: one picture that became more than 4 times the limit is logged with the numbers, so the next report has them (the reader's own
        stderr has the warm-up line).  A reader built before the limit was enforced inside it (strata-vision refuses these now) still lets them by."""
        limit = getattr(self, "max_tokens", 0)
        if limit and tokens > 4 * limit:
            print(f"[strata] images: one picture became {tokens} image tokens, more than 4 times the limit of {limit} (vision.max_tokens); "
                  "the picture reader is not applying its limit. Update the engine, and send the line 'strata-vision: warmed up at N image "
                  "tokens' from the reader's log with the report", flush=True)

    def close(self):
        proc, self.proc = self.proc, None
        if proc is None:
            self.stopped = True
            return
        try:
            proc.stdin.write("QUIT\n")
            proc.stdin.flush()
            proc.wait(timeout=10)
        except Exception:
            try:
                proc.kill()
            except OSError:
                pass
            try:
                proc.wait(timeout=10)
            except (OSError, subprocess.TimeoutExpired):
                pass
        self.stopped = True

    def shutdown(self):
        """#914: close() for good: the server ends, so the encoder's directory (one ~10 MB .sve per image, on a tmpfs
        /tmp that is RAM) goes with it instead of piling up with every start.  unload() keeps it for the restart."""
        self.close()
        shutil.rmtree(self.dir, ignore_errors=True)
