"""Workspace checkpoints (a jj mirror) so a request's changes can be undone.

Moved out of dl_cli.py without changes; see dl_cli.py for the entry point and the names tests patch."""
from __future__ import annotations

from pathlib import Path
import hashlib
import os
import re
import shlex
import shutil
import stat
import subprocess
import time
try:
    from .dl_common import _note, cli as _cli, dl_memory
except ImportError:
    from dl_common import _note, cli as _cli, dl_memory


# ---------------------------------------------------------------------------------------------------- checkpoints
# 2026-10-20 21:23: a run_command Python edit emptied CONTRA's 33 KB data module, the command still said "exit 0",
# and nothing could undo it (no git, no snapshots). Now every round that changes files is committed to a git history
# kept outside the workspace, and a tool call that empties, deletes or halves a file says so in its result, with the
# command that restores it.
CHECKPOINT_DIR = Path(os.environ.get("DL_CHECKPOINT_DIR") or Path.home() / ".local" / "state" / "dl-ai" / "checkpoints")


CHECKPOINT_MAX_FILES = 20000                   # a bigger folder gets no checkpoints (a notice says so)


CHECKPOINT_MAX_FILE = 20 * 1024 * 1024         # bigger files (models, archives) are left out of the history


SHRINK_MIN = 1024                              # smaller files never raise the shrink alarm


WRITE_TOOLS = ("run_command", "write_to_file", "replace_file_content")


SCAN_SKIP = (".git", ".jj", "node_modules", "__pycache__", ".venv")


SHRINK_NOTE = ("[D.L. CLI] Warning: {what}. If that was not intended, restore it from the checkpoint taken before "
               "this round:\n  {restore}")


def scan_workspace(ws: Path, cap: int | None = None) -> dict[str, tuple[int, int]] | None:
    """{relative path: (size, mtime_ns)} of the folder's regular files, or None when it has more than cap."""
    cap = _cli().CHECKPOINT_MAX_FILES if cap is None else cap
    out: dict[str, tuple[int, int]] = {}
    for root, dirs, files in os.walk(ws):
        dirs[:] = [d for d in dirs if d not in SCAN_SKIP]
        for f in files:
            p = os.path.join(root, f)
            try:
                st = os.lstat(p)
            except OSError:
                continue
            if stat.S_ISREG(st.st_mode):
                out[os.path.relpath(p, ws)] = (st.st_size, st.st_mtime_ns)
                if len(out) > cap:
                    return None
    return out


def shrunk_files(before: dict, after: dict) -> list[tuple[str, str]]:
    """(path, what happened) for the files of at least SHRINK_MIN bytes a tool call emptied, deleted or cut below
    half.  Files in a top-level tmp/ or temp/ folder are scratch and left out."""
    out = []
    for rel, (size, _) in sorted(before.items()):
        if size < SHRINK_MIN or rel.split(os.sep, 1)[0] in ("tmp", "temp"):
            continue
        new = after.get(rel)
        if new is None:
            out.append((rel, f"deleted {rel} ({size:,} bytes)"))
        elif new[0] == 0:
            out.append((rel, f"emptied {rel} ({size:,} -> 0 bytes)"))
        elif new[0] < size // 2:
            out.append((rel, f"cut {rel} from {size:,} to {new[0]:,} bytes"))
    return out


def shrink_note(hits: list[tuple[str, str]], cps: "Checkpoints | None") -> str:
    what = "this call " + "; ".join(h[1] for h in hits[:5]) + (f"; and {len(hits) - 5} more" if len(hits) > 5 else "")
    if cps is not None and cps.head:
        restore = cps.restore_command(hits[0][0]) + (" (the same command with another path restores the others)"
                                                      if len(hits) > 1 else "")
        return SHRINK_NOTE.format(what=what, restore=restore)
    why = f" ({cps.off})" if cps is not None and cps.off else ""
    return f"[D.L. CLI] Warning: {what}. There is no checkpoint to restore it from{why}: check that it was intended."



class Checkpoints:
    """A jj history of one workspace, kept outside it in CHECKPOINT_DIR and committed after every round that changed
    files, so an edit by any tool - a shell command included - can be undone.  The history lives in a mirror folder:
    each checkpoint copies the workspace's changed files into it and `jj commit`s them there, so the workspace itself
    gets no .jj or .git folder.  The workspace's own .gitignore files apply (jj reads them in the mirror); files over
    CHECKPOINT_MAX_FILE are left out.  Ray uses jj, not git (the user's rule, 2026-11-14).  Off with DL_CHECKPOINTS=0,
    and for the home folder, / and folders with more than CHECKPOINT_MAX_FILES files."""

    def __init__(self, ws: Path, emit=None):
        self.ws = Path(ws).resolve()
        key = hashlib.sha256(str(self.ws).encode()).hexdigest()[:12]
        self.repo = _cli().CHECKPOINT_DIR / f"{re.sub(r'[^A-Za-z0-9_.-]', '_', self.ws.name) or 'root'}-{key}.jj"
        self.emit = emit
        self.head: str | None = None
        self.files: dict | None = None             # the scan the last checkpoint was taken from
        self.off = ""
        self.jj = (dl_memory.resolve_jj_bin() if dl_memory is not None else None) or shutil.which("jj")
        if os.environ.get("DL_CHECKPOINTS", "1") == "0":
            self.off = "DL_CHECKPOINTS=0"
        elif not self.jj:
            self.off = "jj is not installed"
        elif self.ws in (Path.home().resolve(), Path("/")):
            self.off = f"{self.ws} is too broad a folder"

    def _jj(self, *args: str, timeout: int = 120) -> subprocess.CompletedProcess:
        env = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "JJ_"))}
        env["JJ_CONFIG"] = os.devnull                 # the user's own jj settings never change the checkpoints
        cfg = ["--config", "user.name=D.L. CLI", "--config", "user.email=dl-cli@localhost",
               "--config", f"snapshot.max-new-file-size={_cli().CHECKPOINT_MAX_FILE + 1}", "--config", "ui.color=never"]
        return subprocess.run([self.jj, "--no-pager", "-R", str(self.repo), *cfg, *args],
                              capture_output=True, text=True, timeout=timeout, env=env, cwd=self.repo)

    def _disable(self, why: str) -> None:
        self.off = why
        _note(self.emit, f"Checkpoints are off for {self.ws}: {why}.", "warn")

    def changed_since(self, start: str | None) -> list[str]:
        """Paths changed between the checkpoint `start` and the latest one, by any tool (shell commands too)."""
        if self.off or not start or not self.head or start == self.head:
            return []
        try:
            out = self._jj("diff", "--ignore-working-copy", "--from", start, "--to", self.head, "--name-only").stdout
        except (OSError, subprocess.TimeoutExpired):
            return []
        return [n for n in out.splitlines() if n]

    def diff_since(self, start: str, limit: int, per_file: int = 6000) -> str:
        """The diff since `start`, smallest files first; a file whose diff is over per_file (a built page, an
        assembled harness) is named with its size instead, so the hand-written changes fit in `limit`."""
        parts, big = [], []
        for name in self.changed_since(start):
            try:
                d = self._jj("diff", "--ignore-working-copy", "--git", "--context", "2", "--from", start,
                             "--to", self.head, f'root-file:"{name}"').stdout
            except (OSError, subprocess.TimeoutExpired):
                continue
            (big if len(d) > per_file else parts).append((len(d), name, d))
        text, used = [], 0
        for size, name, d in sorted(parts):
            if used + size > limit:
                big.append((size, name, ""))
                continue
            text.append(d)
            used += size
        if big:
            text.append("[left out of this diff, too long: " + ", ".join(f"{n} ({s:,} chars)" for s, n, _ in
                                                                         sorted(big, reverse=True)) + "]")
        return "\n".join(text)

    def restore_command(self, rel: str) -> str:
        """A plain copy (no jj or git) of the file as checkpoint `head` has it.  The mirror holds that version until
        the next checkpoint, so it is saved now under <repo>-restore/<head>/; saved copies older than 7 days go."""
        keep = self.repo.parent / f"{self.repo.name}-restore"
        src, saved, dst = self.repo / rel, keep / str(self.head) / rel, self.ws / rel
        try:
            if not saved.is_file() and src.is_file():
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, saved)
            cutoff = time.time() - 7 * 86400
            for old in keep.iterdir():
                if old.is_dir() and old.stat().st_mtime < cutoff:
                    shutil.rmtree(old, ignore_errors=True)
        except OSError:
            pass
        return f"mkdir -p {shlex.quote(str(dst.parent))} && cp -p {shlex.quote(str(saved))} {shlex.quote(str(dst))}"

    def _sync(self, files: dict) -> None:
        """Make the mirror hold the workspace's files (big ones left out); copies only what changed."""
        old = self.files or {}
        keep = {rel for rel, (size, _) in files.items() if size <= _cli().CHECKPOINT_MAX_FILE}
        for root, dirs, names in os.walk(self.repo):
            dirs[:] = [d for d in dirs if not (root == str(self.repo) and d == ".jj")]
            for n in names:
                rel = os.path.relpath(os.path.join(root, n), self.repo)
                if rel not in keep:
                    os.unlink(os.path.join(root, n))
        for rel in keep:
            dst = self.repo / rel
            if old.get(rel) == files[rel] and dst.is_file():
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(self.ws / rel, dst)
            except OSError:
                pass                                  # gone or unreadable since the scan: left as it was

    def take(self, label: str) -> str | None:
        """Commit the workspace if it changed since the last checkpoint; the new commit's short id, else None."""
        if self.off:
            return None
        files = scan_workspace(self.ws)
        if files is None:
            self._disable(f"it has more than {_cli().CHECKPOINT_MAX_FILES:,} files")
            return None
        if files == self.files:
            return None
        try:
            if not (self.repo / ".jj").is_dir():
                self.repo.mkdir(parents=True, exist_ok=True, mode=0o700)
                r = subprocess.run([self.jj, "--no-pager", "git", "init", "--no-colocate", str(self.repo)],
                                   capture_output=True, text=True, timeout=60,
                                   env={**{k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "JJ_"))},
                                        "JJ_CONFIG": os.devnull})
                if r.returncode:
                    self._disable(f"jj init failed: {(r.stderr or r.stdout).strip()[:200]}")
                    return None
                _note(self.emit, f"Checkpoints of {self.ws} are kept in {self.repo} (a jj history, committed "
                                 "after every round that changes files; DL_CHECKPOINTS=0 turns them off).")
            self._sync(files)
            self.files = files
            r = self._jj("diff", "--summary")         # snapshots the mirror; empty when only mtimes changed
            if r.returncode:
                self._disable(f"jj snapshot failed: {(r.stderr or r.stdout).strip()[:200]}")
                return None
            if self.head is None and not r.stdout.strip():      # a new request, nothing changed: reuse the last one
                last = self._jj("log", "--ignore-working-copy", "--no-graph", "-r", "@- ~ root()", "-T",
                                "commit_id.short(10)").stdout.strip()
                self.head = last or None
            if not r.stdout.strip() and self.head:
                return None
            r = self._jj("commit", "-m", label[:200])
            if r.returncode:
                self._disable(f"jj commit failed: {(r.stderr or r.stdout).strip()[:200]}")
                return None
            self.head = self._jj("log", "--ignore-working-copy", "--no-graph", "-r", "@-", "-T",
                                 "commit_id.short(10)").stdout.strip() or None
        except (OSError, subprocess.TimeoutExpired) as e:
            self._disable(str(e)[:200])
            return None
        return self.head
