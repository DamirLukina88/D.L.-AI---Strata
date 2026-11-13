#!/usr/bin/env python3
"""dl_memory.py - Consolidated Jujutsu (jj) + SQLite FTS5 + Model2Vec memory engine.

Unified long-term memory backend for Ray (dl_cli.py / dl_sessiond.py), Claude Code,
and Antigravity. Stores human-readable Markdown pages in one configured directory
(global/, projects/<slug>/, handoffs/<scope>/), keeps an incremental SQLite FTS5 +
Model2Vec index (.memory/index.db), versions every mutation atomically with jj, and
isolates credentials in a .gitignore'd private/ vault.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Any
from urllib.parse import unquote

try:
    import numpy as np
except ImportError:  # pragma: no cover - numpy optional fallback
    np = None  # type: ignore[assignment]

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))
if str(TOOLS_DIR.parent) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR.parent))

try:
    from tools import dl_auditing, dl_router  # type: ignore
except ImportError:
    try:
        import dl_auditing  # type: ignore
    except ImportError:  # pragma: no cover
        dl_auditing = None  # type: ignore[assignment]
    try:
        import dl_router  # type: ignore
    except ImportError:  # pragma: no cover
        dl_router = None  # type: ignore[assignment]

CONFIG_PATH = Path(os.environ.get("RAY_MEMORY_CONFIG") or Path.home() / ".config" / "dl-ai" / "memory.json")
CACHE_DIR = Path(os.environ.get("RAY_MEMORY_CACHE") or Path.home() / ".cache" / "ray-memory")

REQUIRED_KEYS = ("title", "type", "description", "status", "tags", "created", "updated", "last_verified")
TYPES = {"concept", "entity", "decision", "preference", "log", "artifact", "index"}
FOLDERS = {
    "concept": "concepts",
    "entity": "entities",
    "decision": "decisions",
    "preference": "preferences",
    "log": "logs",
    "artifact": "artifacts",
}
STATUSES = {"active", "superseded", "deprecated"}
DATE_KEYS = ("created", "updated", "last_verified")
NO_STALE_CHECK = {"log", "artifact", "index"}
PRIVATE_DIR = "private"
ENV_REL = "private/.env"
MEMORY_DIR = ".memory"
INDEX_REL = ".memory/index.db"
LOCK_REL = ".memory/write.lock"
PROJECTS_REL = "projects.json"
META_FILENAMES = {"index.md", "changelog.md", "README.md"}
KEBAB_MD = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*\.md$")
LINK_RE = re.compile(r"!?\[[^\]]*\]\(\s*(?:<([^>]+)>|([^)\s]+))(?:\s+\"[^\"]*\")?\s*\)")
INLINE_CODE_RE = re.compile(r"`[^`]*`")
ABS_PATH_CODE_RE = re.compile(r"`(~/[^`\s]*|/[^`\s/]+/[^`\s]*)`")

GITIGNORE_LINES = ["private/", ".memory/", ".trash/", "handoffs/", "*.db", "*.db-wal", "*.db-shm", "*.lock", "*.tmp"]
GITIGNORE_TEXT = (
    "# Ray Consolidated Memory: credentials, indexes, locks and session handoffs (conversation text) are never\n"
    "# versioned.\n" + "".join(f"{x}\n" for x in GITIGNORE_LINES)
)
# Never walked by the working-copy guard: jj ignores them (above) or they are jj's / git's own.
UNTRACKED_TOP = {".jj", ".git", PRIVATE_DIR, ".memory", ".trash", "handoffs"}
HANDOFF_KEEP_DAYS = 30
GLOBAL_APPROVAL_MSG = ("Error: writing global/ needs the user's approval (global pages reach every agent in every "
                       "project). Ray asks on a card; Claude Code and Antigravity use the memory_write_global tool, "
                       "which their permission prompt guards; in a terminal, `dl_memory.py` asks on the keyboard.")

STOPWORDS = {
    "the", "and", "for", "with", "what", "how", "why", "about", "that", "this",
    "from", "into", "are", "was", "we", "our", "do", "does", "is", "of", "to",
    "in", "on", "a", "an", "or",
}

FALLBACK_SECRETS = [
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}")),
    ("GitHub token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,}")),
    ("GitLab token", re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}")),
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    ("API key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}")),
    ("Stripe key", re.compile(r"\b[rs]k_live_[A-Za-z0-9]{16,}")),
    ("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("Hugging Face token", re.compile(r"\bhf_[A-Za-z0-9]{30,}")),
    ("npm token", re.compile(r"\bnpm_[A-Za-z0-9]{36}")),
    ("connection string with password", re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s/:@]+:[^\s/@]{3,}@[^\s/]+")),
]

DEFAULT_CAPS = {
    "digest_chars": 3000,
    "digest_tokens": 1500,
    "reminder_tokens": 400,
    "nudge_edits": 5,
}

# --------------------------------------------------------------------------- config & path resolution


def config_path() -> Path:
    env = os.environ.get("RAY_MEMORY_CONFIG", "").strip()
    return Path(env).expanduser() if env else CONFIG_PATH


def load_config() -> dict[str, Any]:
    p = config_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def resolve_memory_root(workspace: Path | None = None, *, require_exists: bool = True) -> Path | None:
    """Resolve the consolidated memory root from RAY_MEMORY_DIR or ~/.config/dl-ai/memory.json."""
    if "RAY_MEMORY_DIR" in os.environ:
        raw = os.environ["RAY_MEMORY_DIR"].strip()
        if not raw or raw.lower() in ("off", "none", "0", "false"):
            return None
        root = Path(raw).expanduser().resolve()
        return root if (not require_exists or root.is_dir()) else None
    cfg = load_config()
    raw_root = str(cfg.get("root") or "").strip()
    if not raw_root:
        return None
    root = Path(raw_root).expanduser().resolve()
    return root if (not require_exists or root.is_dir()) else None


def resolve_jj_bin() -> str | None:
    env_jj = os.environ.get("RAY_JJ_BIN", "").strip()
    if env_jj:
        p = Path(env_jj).expanduser()
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)
        found = shutil.which(env_jj)
        if found:
            return found
    cfg_jj = str(load_config().get("jj_bin") or "").strip()
    if cfg_jj:
        p = Path(cfg_jj).expanduser()
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)
    return shutil.which("jj")


def detect_agent() -> str:
    if os.environ.get("RAY_MEMORY_AGENT"):
        return os.environ["RAY_MEMORY_AGENT"].strip()
    if os.environ.get("LOCAL_WIKI_AGENT"):
        return os.environ["LOCAL_WIKI_AGENT"].strip()
    if os.environ.get("CLAUDECODE"):
        return "Claude Code"
    if any(k.upper().startswith(("ANTIGRAVITY", "AGY_")) for k in os.environ):
        return "Antigravity"
    return "Ray"


def slugify(text: str, fallback: str = "project") -> str:
    """'CLAUDE SVAŠTARA' -> 'claude-svastara' (accents folded, not dropped)."""
    import unicodedata
    folded = unicodedata.normalize("NFKD", (text or "").replace("đ", "dj").replace("Đ", "Dj"))
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9]+", "-", folded.lower()).strip("-")
    return s or fallback


# --------------------------------------------------------------------------- project registry


def _load_projects(root: Path) -> dict[str, Any]:
    p = root / PROJECTS_REL
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data.setdefault("by_path", {})
            data.setdefault("projects", {})
            return data
    except (OSError, ValueError):
        pass
    return {"by_path": {}, "projects": {}}


def _save_projects(root: Path, data: dict[str, Any]) -> None:
    p = root / PROJECTS_REL
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(p)


def resolve_project_slug(workspace: Path | str | None, root: Path, *, register: bool = False) -> str:
    """Map an active workspace path (resolving symlinks) to its canonical project slug."""
    if not workspace:
        return "global"
    ws = Path(workspace).expanduser().resolve()
    ws_str = str(ws)
    data = _load_projects(root)
    by_path: dict[str, str] = data["by_path"]
    projects: dict[str, dict[str, Any]] = data["projects"]

    if ws_str in by_path:
        return by_path[ws_str]

    # Match longest registered parent directory (e.g., Strata/serve -> strata)
    best_match = ""
    best_slug = ""
    for reg_path, slug in by_path.items():
        if ws_str.startswith(reg_path.rstrip("/") + "/") and len(reg_path) > len(best_match):
            best_match = reg_path
            best_slug = slug
    if best_slug:
        return best_slug

    base_slug = slugify(ws.name, fallback="workspace")
    slug = base_slug
    idx = 2
    while slug in projects and ws_str not in (projects[slug].get("paths") or []):
        slug = f"{base_slug}-{idx}"
        idx += 1

    if register:
        by_path[ws_str] = slug
        entry = projects.setdefault(slug, {"name": ws.name, "paths": []})
        if ws_str not in entry["paths"]:
            entry["paths"].append(ws_str)
        _save_projects(root, data)
    return slug


def list_projects(root: Path) -> list[dict[str, Any]]:
    data = _load_projects(root)
    out = []
    proj_dir = root / "projects"
    disk_slugs = {p.name for p in proj_dir.iterdir() if p.is_dir()} if proj_dir.is_dir() else set()
    all_slugs = sorted(set(data["projects"].keys()) | disk_slugs)
    for slug in all_slugs:
        meta = data["projects"].get(slug, {})
        count = sum(1 for f in (proj_dir / slug).rglob("*.md")
                    if f.name not in META_FILENAMES and not any(part.startswith(".") for part in f.parts)) if (proj_dir / slug).is_dir() else 0
        out.append({"slug": slug, "name": meta.get("name") or slug, "paths": meta.get("paths") or [], "pages": count})
    return out


# --------------------------------------------------------------------------- locking & jj VCS


@contextlib.contextmanager
def write_lock(root: Path):
    mem_dir = root / MEMORY_DIR
    mem_dir.mkdir(parents=True, exist_ok=True)
    lock_path = root / LOCK_REL
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _run_jj(root: Path, args: list[str], timeout: int = 30, *, snapshot: bool = False) -> subprocess.CompletedProcess[str]:
    """Every jj command records the folder's current files first (a "snapshot") unless told not to, so a token an agent
    wrote into a page would enter jj's history on a mere `jj log`.  Reads pass --ignore-working-copy; a call with
    snapshot=True must hold write_lock, and runs the working-copy guard first so jj only ever sees scanned files."""
    jj = resolve_jj_bin()
    if not jj:
        raise RuntimeError("jj binary not found (install jj or configure RAY_JJ_BIN / memory.json)")
    if snapshot:
        _guard_working_copy(root)
    return subprocess.run(
        [jj, "--no-pager", "--color", "never", *([] if snapshot else ["--ignore-working-copy"]), *args],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _fileset(rels: list[str]) -> list[str]:
    """jj file patterns that match exactly these store-relative paths (spaces and quotes included)."""
    return ['root-file:"' + r.replace("\\", "\\\\").replace('"', '\\"') + '"' for r in rels]


def ensure_gitignore(root: Path) -> bool:
    """Add any missing line of GITIGNORE_LINES; True when the file changed."""
    gi = root / ".gitignore"
    old = gi.read_text(encoding="utf-8", errors="replace") if gi.is_file() else ""
    have = {ln.strip() for ln in old.splitlines()}
    missing = [x for x in GITIGNORE_LINES if x not in have]
    if not old:
        gi.write_text(GITIGNORE_TEXT, encoding="utf-8")
        return True
    if missing:
        gi.write_text(old.rstrip("\n") + "\n" + "".join(f"{x}\n" for x in missing), encoding="utf-8")
        return True
    return False


# --------------------------------------------------------------------------- working-copy guard


def _tracked_files(root: Path):
    """(path, rel) of every file jj would track: everything under root except the ignored folders and patterns."""
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = Path(dirpath).relative_to(root)
        if rel_dir == Path("."):
            dirnames[:] = sorted(d for d in dirnames if d not in UNTRACKED_TOP)
        else:
            dirnames[:] = sorted(dirnames)
        for fname in sorted(filenames):
            if fname.endswith((".db", ".db-wal", ".db-shm", ".lock", ".tmp")):
                continue
            p = Path(dirpath) / fname
            if p.is_symlink() or not p.is_file():
                continue
            yield p, p.relative_to(root).as_posix()


def _vetted(con: sqlite3.Connection) -> dict[str, tuple[str, int]]:
    return {r["rel_path"]: (r["sha256"], r["global_ok"]) for r in con.execute("SELECT * FROM vetted").fetchall()}


def _approve_paths(root: Path, rels: list[str], *, global_ok: bool) -> None:
    """Record these files' current content as scanned (and, for global/, approved by the user)."""
    con = _connect_db(root)
    try:
        with con:
            for rel in rels:
                p = root / rel
                if p.is_file():
                    sha = hashlib.sha256(p.read_bytes()).hexdigest()
                    con.execute("INSERT OR REPLACE INTO vetted (rel_path, sha256, global_ok) VALUES (?, ?, ?)",
                                (rel, sha, 1 if global_ok else 0))
                else:
                    con.execute("DELETE FROM vetted WHERE rel_path = ?", (rel,))
    finally:
        con.close()


def _committed_text(root: Path, rel: str) -> bytes | None:
    res = subprocess.run([resolve_jj_bin() or "jj", "--no-pager", "--ignore-working-copy", "file", "show", "-r", "@-",
                          *_fileset([rel])], cwd=root, capture_output=True, timeout=30)
    return res.stdout if res.returncode == 0 and res.stdout else None


def _guard_working_copy(root: Path) -> list[str]:
    """Run under write_lock before any jj snapshot.  Every tracked file whose content has not been scanned yet is
    scanned for credentials; a file under global/ must also carry the user's approval (recorded by the approved
    write paths).  A file that fails is moved to .memory/quarantine/<time>/ and its last committed version is put
    back (or nothing, for a new file); a global/ page deleted without approval is restored.  Returns one line per
    file it acted on."""
    reports: list[str] = []
    leaked = False
    con = _connect_db(root)
    try:
        vetted = _vetted(con)
        seen: set[str] = set()
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        for path, rel in _tracked_files(root):
            seen.add(rel)
            try:
                data = path.read_bytes()
            except OSError:
                continue
            sha = hashlib.sha256(data).hexdigest()
            prev = vetted.get(rel)
            is_global = rel.startswith("global/")
            if prev and prev[0] == sha and (prev[1] or not is_global):
                continue
            problem = secret_error(data.decode("utf-8", errors="replace"), rel)
            leaked = leaked or bool(problem)
            if not problem and is_global:
                problem = "global/ page changed without the user's approval"
            if not problem:
                with con:
                    con.execute("INSERT OR REPLACE INTO vetted (rel_path, sha256, global_ok) VALUES (?, ?, 0)", (rel, sha))
                continue
            qdir = root / MEMORY_DIR / "quarantine" / stamp
            (qdir / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(qdir / rel))
            old = _committed_text(root, rel) if (root / ".jj").is_dir() else None
            if old is not None:
                path.write_bytes(old)
                with con:
                    con.execute("INSERT OR REPLACE INTO vetted (rel_path, sha256, global_ok) VALUES (?, ?, ?)",
                                (rel, hashlib.sha256(old).hexdigest(), 1 if is_global else 0))
            reports.append(f"{rel}: {problem.removeprefix('Error: ')} — moved to "
                           f"{(qdir / rel).relative_to(root).as_posix()}"
                           + ("; the last committed version is back" if old is not None else ""))
        for rel, (_, ok) in vetted.items():
            if rel.startswith("global/") and rel not in seen and ok:
                old = _committed_text(root, rel) if (root / ".jj").is_dir() else None
                if old is not None:
                    (root / rel).parent.mkdir(parents=True, exist_ok=True)
                    (root / rel).write_bytes(old)
                    reports.append(f"{rel}: deleted without the user's approval — restored")
    finally:
        con.close()
    if leaked and (root / ".jj").is_dir():
        reports.append(_purge_jj_records(root))
    if reports:
        try:
            log = root / MEMORY_DIR / "quarantine" / "log.txt"
            log.parent.mkdir(parents=True, exist_ok=True)
            with open(log, "a", encoding="utf-8") as fh:
                fh.write("".join(f"{dt.datetime.now().isoformat(timespec='seconds')} {r}\n" for r in reports))
        except OSError:
            pass
        _LAST_GUARD.extend(reports)
    return reports


def _purge_jj_records(root: Path) -> str:
    """A credential was found in a file, so a jj command run outside this module (someone typing `jj st` in the
    store) may already have recorded it.  With the file restored: record the clean state, add one more operation so
    no kept operation points at the leaky snapshot, drop every older operation (jj undo history, not commits), and
    garbage-collect jj and git so the leaked text is gone from disk."""
    jj = resolve_jj_bin() or "jj"
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")

    def run(*args: str) -> int:
        return subprocess.run([jj, "--no-pager", *args], cwd=root, capture_output=True, text=True, timeout=120).returncode
    run("status")                                          # the clean files, now that the leak is quarantined
    run("describe", "-r", "@", "-m", f"working copy (history purged {stamp})")
    run("op", "abandon", "..@-")
    run("util", "gc", "--expire=now")
    try:
        target = (root / ".jj" / "repo" / "store" / "git_target").read_text(encoding="utf-8").strip()
        git_dir = (root / ".jj" / "repo" / "store" / target).resolve()
        subprocess.run(["git", f"--git-dir={git_dir}", "-c", "gc.reflogExpire=now", "-c",
                        "gc.reflogExpireUnreachable=now", "gc", "--prune=now", "--quiet"],
                       capture_output=True, timeout=300)
    except (OSError, subprocess.SubprocessError):
        return "jj records purged, but git gc did not run; run `git gc --prune=now` in the store's git folder"
    return "jj operation history purged (commits kept) so the quarantined text is not left in jj or git"


_LAST_GUARD: list[str] = []


def take_guard_reports() -> list[str]:
    """The guard's reports since the last call (shown to the agent whose action ran the guard)."""
    out = list(_LAST_GUARD)
    _LAST_GUARD.clear()
    return out


def init_repo(root: Path) -> Path:
    """Initialize a consolidated jj-backed memory repository at root."""
    root = Path(root).expanduser().resolve()
    for sub in (
        root / MEMORY_DIR,
        root / PRIVATE_DIR,
        root / "projects",
        root / "handoffs",
        *[root / "global" / folder for folder in FOLDERS.values()],
    ):
        sub.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(root / PRIVATE_DIR, 0o700)
    except OSError:
        pass
    ensure_gitignore(root)
    if not (root / PROJECTS_REL).is_file():
        _save_projects(root, {"by_path": {}, "projects": {}})
    with write_lock(root):
        if not (root / ".jj").is_dir():
            res = _run_jj(root, ["git", "init", "."], snapshot=True)
            if res.returncode != 0:
                raise RuntimeError(f"jj git init failed: {(res.stderr or res.stdout).strip()}")
            _run_jj(root, ["config", "set", "--repo", "user.name", "Ray Memory"], snapshot=True)
            _run_jj(root, ["config", "set", "--repo", "user.email", "ray@localhost"], snapshot=True)
            _run_jj(root, ["metaedit", "--update-author"], snapshot=True)
        _jj_commit(root, "init: initialize consolidated ray-memory repo", [".gitignore", PROJECTS_REL])
        sync_index(root)
    return root


def _jj_commit(root: Path, message: str, paths: list[str]) -> str | None:
    """Commit only `paths` (store-relative; deleted files included).  Other agents' uncommitted edits stay in the
    working copy for their own hook to commit under their own name.  Call under write_lock."""
    if not (root / ".jj").is_dir() or not paths:
        return None
    rels = sorted(set(paths))
    diff_res = _run_jj(root, ["diff", "--name-only", *_fileset(rels)], snapshot=True)
    if diff_res.returncode != 0 or not (diff_res.stdout or "").strip():
        return None
    res = _run_jj(root, ["commit", "-m", message[:200], *_fileset(rels)], snapshot=True)
    if res.returncode != 0:
        raise RuntimeError(f"jj commit failed: {(res.stderr or res.stdout).strip()}")
    rev_res = _run_jj(root, ["log", "-r", "@-", "--no-graph", "-T", 'change_id.short(8) ++ " " ++ commit_id.short(8)'])
    return (rev_res.stdout or "").strip() or None


def jj_history(root: Path, scope: str | None = None, workspace: Path | None = None, limit: int = 15) -> str:
    if not (root / ".jj").is_dir():
        return "Memory repository has no .jj history yet."
    args = [
        "log",
        "-r",
        "::@- ~ root()",                     # committed history only, not the working-copy commit on top
        "-n",
        str(max(1, min(limit, 50))),
        "--no-graph",
        "-T",
        'change_id.short(8) ++ " | " ++ commit_id.short(8) ++ " | " ++ committer.timestamp().ago() ++ " | " ++ description.first_line() ++ "\n"',
    ]
    if scope == "global":
        args.append("global")
    elif scope == "project" and workspace:
        slug = resolve_project_slug(workspace, root, register=False)
        proj_dir = root / "projects" / slug
        if proj_dir.is_dir():
            args.append(f"projects/{slug}")
    res = _run_jj(root, args)
    if res.returncode != 0:
        return f"Error reading jj history: {(res.stderr or res.stdout).strip()}"
    lines = [ln for ln in (res.stdout or "").splitlines() if ln.strip() and not ln.startswith("zzzzzzzz")]
    return "\n".join(lines) if lines else "No memory commits yet."


def jj_diff(root: Path, rev: str = "@-") -> str:
    if not (root / ".jj").is_dir():
        return "Memory repository has no .jj history yet."
    rev = (rev or "@-").strip()
    res = _run_jj(root, ["diff", "-r", rev, "--", "global", "projects", "handoffs", "projects.json"])
    if res.returncode != 0:
        return f"Error running jj diff for {rev}: {(res.stderr or res.stdout).strip()}"
    out = (res.stdout or "").strip()
    return out or f"No tracked changes in {rev}."


def jj_undo(root: Path, rev: str = "@-", agent: str | None = None, *, approved: bool = False) -> str:
    """Revert one memory commit (a new commit that undoes it; history keeps both).  Reverting a commit that touched
    global/ changes pages every agent sees, so it needs the same approval as a global write."""
    if not (root / ".jj").is_dir():
        return "Error: memory repository is not initialized with jj."
    rev = (rev or "@-").strip()
    with write_lock(root):
        check = _run_jj(root, ["log", "-r", rev, "--no-graph", "-T", 'change_id.short(8) ++ "|" ++ description.first_line()'])
        if check.returncode != 0:
            return f"Error: revision {rev!r} not found: {(check.stderr or check.stdout).strip()}"
        info = (check.stdout or "").strip()
        if not info or "\n" in info:
            return f"Error: {rev!r} must name exactly one commit."
        if info.startswith("zzzzzzzz") or rev == "root()":
            return "Error: cannot revert the root commit."
        files = (_run_jj(root, ["diff", "--name-only", "-r", rev]).stdout or "").split()
        if any(f.startswith("global/") for f in files) and not approved:
            return GLOBAL_APPROVAL_MSG
        op_res = _run_jj(root, ["op", "log", "-n", "1", "--no-graph", "-T", "self.id().short()"])
        prior_op = (op_res.stdout or "").strip()

        rev_res = _run_jj(root, ["revert", "-r", rev, "-B", "@"], snapshot=True)
        if rev_res.returncode != 0:
            return f"Error reverting {rev}: {(rev_res.stderr or rev_res.stdout).strip()}"
        conf = _run_jj(root, ["log", "-r", "conflicts()", "--no-graph", "-T", "change_id.short(8)"])
        if (conf.stdout or "").strip() and prior_op:
            _run_jj(root, ["op", "restore", prior_op], snapshot=True)
            return f"Error: reverting {rev} caused a conflict; cleanly restored prior operation ({prior_op})."
        _approve_paths(root, files, global_ok=True)        # before the next snapshot, or the guard would undo it
        cid, _, desc = info.partition("|")
        _run_jj(root, ["describe", "-r", "@-", "-m", f"{agent or detect_agent()}: revert {cid} ({desc[:80]})"],
                snapshot=True)
        sync_index(root)
        return (f"Reverted {info.replace('|', ' — ')} ({len(files)} file(s): {', '.join(files[:5])}); "
                "index re-synced. `memory history` shows the revert commit.")


# --------------------------------------------------------------------------- markdown parsing & secrets


def parse_frontmatter(lines: list[str]) -> tuple[dict[str, Any], str | None, int]:
    if not lines or lines[0].strip() != "---":
        return {}, "missing frontmatter", 0
    meta: dict[str, Any] = {}
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return meta, None, i + 1
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, sep, value = line.partition(":")
        if not sep:
            return meta, f"unparseable frontmatter line {i + 1}", i + 1
        value = value.strip()
        if value.startswith(('"', "'")):
            q = value[0]
            end = value.find(q, 1)
            value = value[1:end] if end > 0 else value[1:]
        else:
            value = re.sub(r"\s+#.*$", "", value).strip()
        if value.startswith("[") and value.endswith("]"):
            value = [v.strip().strip("\"'") for v in value[1:-1].split(",") if v.strip()]
        meta[key.strip()] = value
    return meta, "unterminated frontmatter", len(lines)


def parse_date(val: Any) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(val))
    except (TypeError, ValueError):
        return None


def find_secrets(text: str) -> list[tuple[int, str]]:
    """Return [(line_number, label)] for any credential-like strings in text."""
    hits: list[tuple[int, str]] = []
    for n, line in enumerate((text or "").splitlines(), start=1):
        matched = False
        if dl_auditing is not None:
            for label, pat in dl_auditing.SECRET_PATTERNS:
                if pat.search(line):
                    hits.append((n, label))
                    matched = True
                    break
        else:
            for label, pat in FALLBACK_SECRETS:
                if pat.search(line):
                    hits.append((n, label))
                    matched = True
                    break
        if not matched and dl_auditing is not None:
            known = dl_auditing.find_known_secrets(line)
            if known:
                hits.append((n, known[0]))
    return hits


def secret_error(text: str, label_path: str = "memory page") -> str | None:
    if dl_auditing is not None:
        ok, err = dl_auditing.scan_secrets_in_text(text, label_path)
        if not ok:
            return err
    hits = find_secrets(text)
    if hits:
        return f"Potential secret detected at line {hits[0][0]} ({hits[0][1]}). Store credentials in private/.env via `env set`."
    return None


def _body_lines(lines: list[str], body_start: int):
    in_fence = False
    for n, line in enumerate(lines[body_start:], start=body_start + 1):
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if not in_fence:
            yield n, line


def _links_in(line: str):
    for angled, plain in LINK_RE.findall(INLINE_CODE_RE.sub("", line)):
        target = angled or plain
        if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I) or target.startswith("#"):
            continue
        yield target


def _scope_from_rel(rel: str) -> str:
    parts = rel.split("/")
    if parts[0] == "global":
        return "global"
    if parts[0] == "projects" and len(parts) >= 2:
        return parts[1]
    if parts[0] == "handoffs" and len(parts) >= 2:
        return parts[1]
    return parts[0]


# --------------------------------------------------------------------------- SQLite FTS5 + Model2Vec index


def _connect_db(root: Path) -> sqlite3.Connection:
    mem_dir = root / MEMORY_DIR
    mem_dir.mkdir(parents=True, exist_ok=True)
    db_path = root / INDEX_REL
    con = sqlite3.connect(str(db_path), timeout=15.0)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS pages (
            rel_path TEXT PRIMARY KEY,
            scope TEXT NOT NULL,
            type TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            tags TEXT NOT NULL,
            status TEXT NOT NULL,
            superseded_by TEXT NOT NULL,
            updated TEXT NOT NULL,
            last_verified TEXT NOT NULL,
            mtime_ns INTEGER NOT NULL,
            size INTEGER NOT NULL,
            sha256 TEXT NOT NULL,
            embedding BLOB,
            body TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(
            rel_path UNINDEXED,
            scope,
            title,
            tags,
            description,
            body,
            content='pages',
            content_rowid='rowid',
            tokenize='porter unicode61'
        );
        CREATE TRIGGER IF NOT EXISTS pages_ai AFTER INSERT ON pages BEGIN
            INSERT INTO pages_fts(rowid, rel_path, scope, title, tags, description, body)
            VALUES (new.rowid, new.rel_path, new.scope, new.title, new.tags, new.description, new.body);
        END;
        CREATE TRIGGER IF NOT EXISTS pages_ad AFTER DELETE ON pages BEGIN
            INSERT INTO pages_fts(pages_fts, rowid, rel_path, scope, title, tags, description, body)
            VALUES ('delete', old.rowid, old.rel_path, old.scope, old.title, old.tags, old.description, old.body);
        END;
        CREATE TRIGGER IF NOT EXISTS pages_au AFTER UPDATE ON pages BEGIN
            INSERT INTO pages_fts(pages_fts, rowid, rel_path, scope, title, tags, description, body)
            VALUES ('delete', old.rowid, old.rel_path, old.scope, old.title, old.tags, old.description, old.body);
            INSERT INTO pages_fts(rowid, rel_path, scope, title, tags, description, body)
            VALUES (new.rowid, new.rel_path, new.scope, new.title, new.tags, new.description, new.body);
        END;
        CREATE TABLE IF NOT EXISTS vetted (
            rel_path TEXT PRIMARY KEY,
            sha256 TEXT NOT NULL,
            global_ok INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS links (
            src_rel TEXT NOT NULL,
            dst_rel TEXT NOT NULL,
            PRIMARY KEY (src_rel, dst_rel)
        );
        CREATE INDEX IF NOT EXISTS idx_pages_scope_status ON pages(scope, status);
        CREATE INDEX IF NOT EXISTS idx_links_dst ON links(dst_rel);
        """
    )
    return con


def _iter_memory_files(root: Path):
    for top in ("global", "projects", "handoffs"):
        base = root / top
        if not base.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
            for fname in sorted(filenames):
                if not fname.endswith(".md") or fname in META_FILENAMES:
                    continue
                p = Path(dirpath) / fname
                yield p, p.relative_to(root).as_posix()


def _encode_texts(texts: list[str]) -> list[bytes | None]:
    if not texts or dl_router is None or np is None:
        return [None] * len(texts)
    vecs = dl_router.encode(texts, preprocess=False)
    if vecs is None:
        return [None] * len(texts)
    return [np.asarray(v, dtype=np.float32).tobytes() for v in vecs]


def _page_embed_text(title: str, description: str, tags_str: str, body: str) -> str:
    return f"{title}\n{description}\n{tags_str}\n{body[:1500]}".strip()


def sync_index(root: Path, *, force: bool = False, backfill_embeddings: bool = True) -> dict[str, int]:
    """Incrementally synchronize .memory/index.db with Markdown files in root."""
    con = _connect_db(root)
    try:
        existing = {
            row["rel_path"]: (row["mtime_ns"], row["size"], row["embedding"] is not None)
            for row in con.execute("SELECT rel_path, mtime_ns, size, embedding FROM pages").fetchall()
        }
        seen: set[str] = set()
        to_upsert: list[tuple[Any, ...]] = []
        link_rows: list[tuple[str, str]] = []
        embed_queue: list[tuple[int, str]] = []

        for path, rel in _iter_memory_files(root):
            seen.add(rel)
            try:
                st = path.stat()
            except OSError:
                continue
            prev = existing.get(rel)
            if not force and prev and prev[0] == st.st_mtime_ns and prev[1] == st.st_size:
                continue
            try:
                raw = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            lines = raw.splitlines()
            meta, _, body_start = parse_frontmatter(lines)
            body = "\n".join(lines[body_start:]).strip()
            tags_val = meta.get("tags") or []
            tags_str = ", ".join(str(t) for t in tags_val) if isinstance(tags_val, list) else str(tags_val)
            title = str(meta.get("title") or path.stem)
            desc = str(meta.get("description") or "")
            ptype = str(meta.get("type") or "concept")
            status = str(meta.get("status") or "active")
            sup = str(meta.get("superseded_by") or "")
            updated = str(meta.get("updated") or "")
            verified = str(meta.get("last_verified") or "")
            scope = _scope_from_rel(rel)
            sha = hashlib.sha256(raw.encode("utf-8")).hexdigest()

            idx = len(to_upsert)
            embed_queue.append((idx, _page_embed_text(title, desc, tags_str, body)))
            to_upsert.append([
                rel, scope, ptype, title, desc, tags_str, status, sup,
                updated, verified, st.st_mtime_ns, st.st_size, sha, None, body,
            ])

            for _, line in _body_lines(lines, body_start):
                for target in _links_in(line):
                    resolved = (path.parent / unquote(target.split("#", 1)[0])).resolve()
                    try:
                        dst_rel = resolved.relative_to(root.resolve()).as_posix()
                    except ValueError:
                        continue
                    link_rows.append((rel, dst_rel))

        # Backfill missing embeddings if model is now available (e.g. from .venv / MCP)
        backfill_rows: list[tuple[str, str]] = []
        if backfill_embeddings and dl_router is not None and np is not None:
            for row in con.execute(
                "SELECT rel_path, title, description, tags, body FROM pages WHERE embedding IS NULL"
            ).fetchall():
                if row["rel_path"] in seen and not any(u[0] == row["rel_path"] for u in to_upsert):
                    backfill_rows.append((
                        row["rel_path"],
                        _page_embed_text(row["title"], row["description"], row["tags"], row["body"]),
                    ))

        if embed_queue:
            blobs = _encode_texts([t for _, t in embed_queue])
            for (idx, _), blob in zip(embed_queue, blobs):
                to_upsert[idx][13] = blob

        removed = sorted(set(existing.keys()) - seen)
        with con:
            for rel in removed:
                con.execute("DELETE FROM pages WHERE rel_path = ?", (rel,))
                con.execute("DELETE FROM links WHERE src_rel = ?", (rel,))
            for rec in to_upsert:
                con.execute("DELETE FROM links WHERE src_rel = ?", (rec[0],))
                con.execute(
                    """
                    INSERT INTO pages (
                        rel_path, scope, type, title, description, tags, status, superseded_by,
                        updated, last_verified, mtime_ns, size, sha256, embedding, body
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(rel_path) DO UPDATE SET
                        scope=excluded.scope, type=excluded.type, title=excluded.title,
                        description=excluded.description, tags=excluded.tags, status=excluded.status,
                        superseded_by=excluded.superseded_by, updated=excluded.updated,
                        last_verified=excluded.last_verified, mtime_ns=excluded.mtime_ns,
                        size=excluded.size, sha256=excluded.sha256, embedding=excluded.embedding,
                        body=excluded.body
                    """,
                    tuple(rec),
                )
            if link_rows:
                con.executemany("INSERT OR IGNORE INTO links (src_rel, dst_rel) VALUES (?, ?)", link_rows)
            if backfill_rows:
                blobs = _encode_texts([t for _, t in backfill_rows])
                for (rel, _), blob in zip(backfill_rows, blobs):
                    if blob is not None:
                        con.execute("UPDATE pages SET embedding = ? WHERE rel_path = ?", (blob, rel))
        return {"indexed": len(to_upsert), "removed": len(removed), "backfilled": len(backfill_rows), "total": len(seen)}
    finally:
        con.close()


def _fts_terms(query: str) -> list[str]:
    raw_tokens = re.findall(r"[^\s\-./:;,!?\"'()\[\]{}<>]+", (query or "").lower())
    terms = [t for t in raw_tokens if len(t) > 1 and t not in STOPWORDS]
    if not terms:
        terms = [t for t in raw_tokens if t]
    return terms[:12]


def _fts_expr(terms: list[str], op: str = "AND") -> str:
    quoted = []
    for t in terms:
        clean = t.replace('"', "")
        if not clean:
            continue
        quoted.append(f'"{clean}"*' if len(clean) >= 3 else f'"{clean}"')
    return f" {op} ".join(quoted)


def _scope_filter_sql(scope: str, active_project: str | None) -> tuple[str, tuple[Any, ...]]:
    if scope == "global":
        return "AND p.scope = 'global'", ()
    if scope == "project" and active_project and active_project != "global":
        return "AND p.scope = ?", (active_project,)
    if scope == "auto" and active_project and active_project != "global":
        # Auto searches everything while boosting active project & global (still finds cross-project refs)
        return "", ()
    return "", ()


def search(
    root: Path,
    query: str,
    *,
    scope: str = "auto",
    workspace: Path | None = None,
    limit: int = 8,
    sync: bool = True,
) -> list[dict[str, Any]]:
    """Hybrid SQLite FTS5 BM25 + Model2Vec cosine similarity search with RRF fusion."""
    if sync:
        sync_index(root)
    active_project = resolve_project_slug(workspace, root, register=False) if workspace else None
    terms = _fts_terms(query)
    if not terms and not (query or "").strip():
        return []

    con = _connect_db(root)
    try:
        where_extra, where_args = _scope_filter_sql(scope, active_project)
        fts_ranks: dict[str, int] = {}
        rows_by_rel: dict[str, sqlite3.Row] = {}

        # 1. FTS5 BM25 pass (AND first, OR fallback)
        if terms:
            seen_fts: list[sqlite3.Row] = []
            for op in ("AND", "OR"):
                expr = _fts_expr(terms, op=op)
                if not expr:
                    continue
                sql = f"""
                    SELECT p.rel_path, p.scope, p.type, p.title, p.description, p.tags,
                           p.status, p.superseded_by, p.updated, p.body,
                           bm25(pages_fts, 0.0, 1.0, 5.0, 4.0, 3.0, 1.0) AS rank_score
                    FROM pages_fts
                    JOIN pages p ON p.rowid = pages_fts.rowid
                    WHERE pages_fts MATCH ? {where_extra}
                    ORDER BY rank_score ASC
                    LIMIT ?
                """
                try:
                    found = con.execute(sql, (expr, *where_args, max(limit * 4, 24))).fetchall()
                except sqlite3.OperationalError:
                    found = []
                for r in found:
                    if r["rel_path"] not in rows_by_rel:
                        rows_by_rel[r["rel_path"]] = r
                        seen_fts.append(r)
                if len(seen_fts) >= limit:
                    break
            for rank_idx, r in enumerate(seen_fts, start=1):
                fts_ranks[r["rel_path"]] = rank_idx

        # 2. Model2Vec semantic pass
        vec_ranks: dict[str, int] = {}
        vec_sims: dict[str, float] = {}
        q_blobs = _encode_texts([query.strip()]) if query.strip() else [None]
        if q_blobs[0] is not None and np is not None:
            q_vec = np.frombuffer(q_blobs[0], dtype=np.float32)
            vec_sql = f"""
                SELECT rel_path, scope, type, title, description, tags, status, superseded_by, updated, body, embedding
                FROM pages p
                WHERE embedding IS NOT NULL {where_extra}
            """
            candidates = con.execute(vec_sql, where_args).fetchall()
            if candidates:
                mat = np.vstack([np.frombuffer(r["embedding"], dtype=np.float32) for r in candidates])
                if mat.shape[1] == q_vec.shape[0]:
                    sims = mat @ q_vec
                    order = np.argsort(-sims)[: max(limit * 4, 24)]
                    for rank_idx, idx in enumerate(order, start=1):
                        sim = float(sims[idx])
                        if sim < 0.12:
                            continue
                        r = candidates[int(idx)]
                        rel = r["rel_path"]
                        vec_ranks[rel] = rank_idx
                        vec_sims[rel] = sim
                        rows_by_rel.setdefault(rel, r)

        # 3. Reciprocal Rank Fusion + scope & active status weights
        scored: list[tuple[float, dict[str, Any]]] = []
        q_low = (query or "").strip().lower()
        for rel, r in rows_by_rel.items():
            rrf = 0.0
            if rel in fts_ranks:
                rrf += 1.0 / (30.0 + fts_ranks[rel])
            if rel in vec_ranks:
                rrf += 0.85 / (30.0 + vec_ranks[rel]) + max(0.0, vec_sims.get(rel, 0.0)) * 0.02
            title_low = r["title"].lower()
            if q_low and q_low in title_low:
                rrf += 0.03
            if r["rel_path"].startswith("handoffs/"):
                rrf *= 0.85
            if active_project and r["scope"] == active_project:
                rrf *= 1.25
            elif r["scope"] == "global":
                rrf *= 1.15
            if r["status"] != "active":
                rrf *= 0.30

            # Extract compact relevant snippet
            body_txt = r["body"] or ""
            snippet = ""
            for term in terms:
                pos = body_txt.lower().find(term)
                if pos != -1:
                    s0 = max(0, pos - 60)
                    snippet = " ".join(body_txt[s0 : s0 + 180].split())
                    break
            scored.append((
                rrf,
                {
                    "rel_path": rel,
                    "scope": r["scope"],
                    "type": r["type"],
                    "title": r["title"],
                    "description": r["description"],
                    "tags": r["tags"],
                    "status": r["status"],
                    "superseded_by": r["superseded_by"],
                    "updated": r["updated"],
                    "score": round(rrf, 5),
                    "fts_rank": fts_ranks.get(rel),
                    "semantic": round(vec_sims.get(rel, 0.0), 3) if rel in vec_sims else None,
                    "snippet": snippet,
                },
            ))
        scored.sort(key=lambda item: (-item[0], item[1]["rel_path"]))
        return [item[1] for item in scored[:limit]]
    finally:
        con.close()


def format_search_results(hits: list[dict[str, Any]], query: str) -> str:
    if not hits:
        return f"No memories match '{query}'."
    lines = [f"{len(hits)} match(es) for '{query}' (best first):"]
    for h in hits:
        line = f"- [{h['scope']}] {h['rel_path']} — {h['description']}"
        if h["status"] != "active":
            sup = f"; see {h['superseded_by']}" if h["superseded_by"] else ""
            line += f" *({h['status']}{sup})*"
        if h.get("snippet"):
            line += f"\n    … {h['snippet']}"
        lines.append(line)
    return "\n".join(lines)


# --------------------------------------------------------------------------- read, write, remember, handoff


def _safe_rel_path(root: Path, raw_path: str) -> Path | None:
    p = Path(raw_path).expanduser()
    cand = (p if p.is_absolute() else root / p).resolve()
    try:
        rel = cand.relative_to(root.resolve())
    except ValueError:
        return None
    if rel.parts and rel.parts[0] == PRIVATE_DIR:
        return None
    return cand


def read_page(root: Path, page_path: str, workspace: Path | None = None) -> str:
    raw = (page_path or "").strip()
    if not raw:
        return "Error: path required for read."
    if raw.startswith(PRIVATE_DIR + "/") or "/private/" in raw or raw.endswith(".env"):
        return "Error: private/.env and private/ cannot be read directly; ask the user and use `env get KEY --approved`."

    candidates = [raw]
    if not raw.endswith(".md"):
        candidates.append(raw + ".md")
    if workspace:
        slug = resolve_project_slug(workspace, root, register=False)
        candidates.append(f"projects/{slug}/{raw}")
        if not raw.endswith(".md"):
            candidates.append(f"projects/{slug}/{raw}.md")
    candidates.append(f"global/{raw}")
    if not raw.endswith(".md"):
        candidates.append(f"global/{raw}.md")

    for cand in candidates:
        p = _safe_rel_path(root, cand)
        if p is not None and p.is_file():
            rel = p.relative_to(root.resolve()).as_posix()
            return f"Memory Page: {rel}\n\n{p.read_text(encoding='utf-8', errors='replace')}"
    return f"Error: Memory page not found: {page_path}"


def _build_frontmatter(
    title: str, ptype: str, description: str, tags: list[str], today: str, status: str = "active"
) -> str:
    tag_list = ", ".join(tags) if tags else ptype
    safe_title = title.replace('"', "'")
    safe_desc = description.replace('"', "'")
    return (
        f'---\ntitle: "{safe_title}"\ntype: {ptype}\ndescription: "{safe_desc}"\nstatus: {status}\n'
        f"tags: [{tag_list}]\ncreated: {today}\nupdated: {today}\nlast_verified: {today}\n---\n"
    )


def _format_page(
    title: str, ptype: str, description: str, tags: list[str], body_text: str, source: str, today: str
) -> str:
    fm = _build_frontmatter(title, ptype, description, tags, today)
    body = (body_text or "").strip()
    if not body:
        body = f"## Summary\n\n{description}"
    if not body.lstrip().startswith("# "):
        body = f"# {title}\n\n{body}"
    if not re.search(r"^##\s+Sources\s*$", body, re.M):
        body = f"{body.rstrip()}\n\n## Sources\n\n1. {source}\n"
    return fm + "\n" + body.rstrip() + "\n"


def _title_words(title: str) -> set[str]:
    words = (w for w in re.findall(r"[\w.+#-]+", title.lower()) if len(w) > 1 and w not in STOPWORDS)
    return {w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w for w in words}


def _find_similar_titles(root: Path, scope: str, title: str, slug: str) -> list[str]:
    con = _connect_db(root)
    try:
        rows = con.execute("SELECT rel_path, title FROM pages WHERE scope = ? AND status = 'active'", (scope,)).fetchall()
    finally:
        con.close()
    w_new = _title_words(title)
    hits = []
    for r in rows:
        stem = Path(r["rel_path"]).stem
        if stem == slug or r["title"].strip().lower() == title.strip().lower():
            hits.append(f"{r['rel_path']} ({r['title']})")
            continue
        w_old = _title_words(r["title"])
        if w_new and len(w_new & w_old) / len(w_new) >= 0.65:
            hits.append(f"{r['rel_path']} ({r['title']})")
    return hits


def write_page(
    root: Path,
    *,
    page_type: str,
    slug: str,
    title: str,
    description: str,
    content: str = "",
    tags: list[str] | str | None = None,
    scope: str = "auto",
    workspace: Path | None = None,
    source: str | None = None,
    mode: str = "upsert",
    agent: str | None = None,
    force: bool = False,
    approved: bool = False,
) -> str:
    """Create, update, or append a Markdown memory page atomically with secret scan + SQLite + jj commit.
    A global/ page needs approved=True (the caller got the user's yes); a project page needs a workspace."""
    if page_type not in FOLDERS:
        return f"Error: invalid page_type {page_type!r}; expected one of {', '.join(sorted(FOLDERS))}"
    clean_slug = slug[:-3] if slug.endswith(".md") else slug
    if not KEBAB_MD.match(clean_slug + ".md"):
        clean_slug = slugify(clean_slug, fallback="note")
    today = dt.date.today().isoformat()
    src_line = source or f"{agent or detect_agent()}, chat, {today}."
    tag_list = (
        [t.strip() for t in tags.split(",") if t.strip()]
        if isinstance(tags, str)
        else [str(t).strip() for t in (tags or []) if str(t).strip()]
    )

    if scope == "global" and not approved:
        return GLOBAL_APPROVAL_MSG
    if scope != "global" and not workspace:
        return ("Error: no project folder is known for this write; pass the workspace (the project's directory), "
                "or scope='global' for a rule that applies everywhere.")
    with write_lock(root):
        if scope == "global":
            target_scope = "global"
            base_dir = root / "global"
        else:
            target_scope = resolve_project_slug(workspace, root, register=True)
            base_dir = root / "projects" / target_scope

        target = base_dir / FOLDERS[page_type] / f"{clean_slug}.md"
        rel = target.relative_to(root).as_posix()

        if target.is_file() and mode == "create":
            return f"Error: {rel} already exists; update it instead."

        if not target.is_file() and not force and mode == "create":
            dups = _find_similar_titles(root, target_scope, title, clean_slug)
            if dups:
                return "Possible duplicates found (update one of these or pass force=True):\n" + "\n".join(f"- {d}" for d in dups)

        if target.is_file() and mode == "append":
            old = target.read_text(encoding="utf-8", errors="replace")
            lines = old.splitlines()
            meta, _, body_start = parse_frontmatter(lines)
            meta["updated"] = today
            meta["last_verified"] = today
            new_fm = _build_frontmatter(
                str(meta.get("title") or title),
                str(meta.get("type") or page_type),
                str(meta.get("description") or description),
                meta.get("tags") if isinstance(meta.get("tags"), list) else tag_list,
                today,
                status=str(meta.get("status") or "active"),
            )
            # Keep created date if present
            if meta.get("created"):
                new_fm = re.sub(r"(?m)^created:.*$", f"created: {meta['created']}", new_fm, count=1)
            body = "\n".join(lines[body_start:]).strip()
            addition = f"- **{today}:** {(content or description).strip()}"
            if "## Sources" in body:
                head, tail = body.split("## Sources", 1)
                body = f"{head.rstrip()}\n\n{addition}\n\n## Sources{tail}"
            else:
                body = f"{body}\n\n{addition}\n\n## Sources\n\n1. {src_line}"
            full_text = new_fm + "\n" + body.rstrip() + "\n"
        else:
            if target.is_file():
                old = target.read_text(encoding="utf-8", errors="replace")
                meta, _, _ = parse_frontmatter(old.splitlines())
                created_orig = str(meta.get("created") or today)
            else:
                created_orig = today
            full_text = _format_page(title, page_type, description[:148], tag_list, content or description, src_line, today)
            if created_orig != today:
                full_text = re.sub(r"(?m)^created:.*$", f"created: {created_orig}", full_text, count=1)

        err = secret_error(full_text, rel)
        if err:
            return f"Error: not written — {err}"

        target.parent.mkdir(parents=True, exist_ok=True)
        action_verb = "update" if target.is_file() else "add"
        target.write_text(full_text, encoding="utf-8")
        _approve_paths(root, [rel, PROJECTS_REL], global_ok=(target_scope == "global"))
        sync_index(root)
        rev = _jj_commit(root, f"{agent or detect_agent()}: {action_verb} {rel}", [rel, PROJECTS_REL])
        rev_note = f" (jj {rev})" if rev else ""
        guard = take_guard_reports()
        return f"Saved → {rel}{rev_note}" + ("".join(f"\nQuarantined: {g}" for g in guard))


def remember(
    root: Path,
    fact: str,
    *,
    workspace: Path | None = None,
    scope: str = "auto",
    agent: str | None = None,
    approved: bool = False,
) -> str:
    clean = " ".join((fact or "").split()).strip()
    if not clean:
        return "Error: specify the fact, decision, or preference to remember."
    target_scope = scope
    if clean.lower().startswith("global "):
        target_scope = "global"
        clean = clean[7:].strip()
    elif clean.lower().startswith("global:"):
        target_scope = "global"
        clean = clean[7:].strip()

    words = [re.sub(r"[^a-z0-9]", "", w.lower()) for w in clean.split()[:6]]
    slug = "-".join(w for w in words if w) or f"note-{int(dt.datetime.now().timestamp())}"
    return write_page(
        root,
        page_type="preference",
        slug=slug[:60],
        title=clean[:72],
        description=clean[:140],
        content=f"## Summary\n\n- {clean}",
        tags=["preference", target_scope if target_scope != "auto" else "memory"],
        scope=target_scope,
        workspace=workspace,
        mode="upsert",
        agent=agent,
        force=True,
        approved=approved,
    )


def save_handoff(
    root: Path,
    workspace: Path | None,
    diary: str,
    part: int,
    removed: int,
    *,
    stretch_log: str = "",
    task_summary: str = "",
    agent: str | None = None,
) -> tuple[Path, str, str]:
    """Write handoff latest.md + part-N archive into handoffs/<scope>/ with secret redaction (not versioned by jj)."""
    today = dt.date.today().isoformat()
    ts = dt.datetime.now().strftime("%Y-%m-%d-%H%M%S")
    with write_lock(root):
        slug = resolve_project_slug(workspace, root, register=True) if workspace else "global"
        out_dir = root / "handoffs" / slug
        out_dir.mkdir(parents=True, exist_ok=True)
        arch_name = f"handoff-{ts}-part-{part}.md"
        if (out_dir / arch_name).exists():
            arch_name = f"handoff-{ts}-{dt.datetime.now().microsecond // 1000:03d}-part-{part}.md"

        task_clean = re.sub(r'["\\\n\r]', " ", task_summary or "coding session").strip()[:80] or "coding session"
        latest_fm = _build_frontmatter(
            f"Session Handoff Brief ({slug})",
            "artifact",
            f"Active session handoff brief for {slug}",
            ["handoff", "session-diary", slug],
            today,
        )
        latest_body = (
            f"# Session Handoff Brief (Part #{part})\n\n"
            f"- **Project:** `{slug}`\n"
            f"- **Task:** {task_clean}\n"
            f"- **Full stretch archive:** [Part #{part} ({arch_name})]({arch_name})\n"
            f"- **Archived messages:** {removed}\n\n"
            f"{diary.strip()}\n\n"
            f"## Sources\n\n1. Generated by session handoff #{part} on {today}.\n"
        )
        arch_fm = _build_frontmatter(
            f"Session Handoff Diary {ts} Part {part}",
            "artifact",
            f"Handoff #{part} ({removed} messages archived): {task_clean}"[:140],
            ["handoff", "session-diary", slug, f"part-{part}"],
            today,
        )
        arch_body = (
            f"# Session Handoff Diary — Part #{part} ({ts})\n\n"
            f"- **Active handoff brief:** [Latest](latest.md)\n"
            f"- **Cumulative archived messages:** {removed}\n\n"
            f"{diary.strip()}\n\n"
            + (f"## Stretch Tool Log\n\n{stretch_log}\n\n" if stretch_log else "")
            + f"## Sources\n\n1. Generated by session handoff #{part} on {today}.\n"
        )

        clean_latest = _redact_text(latest_fm + "\n" + latest_body)
        clean_arch = _redact_text(arch_fm + "\n" + arch_body)
        latest_path = out_dir / "latest.md"
        arch_path = out_dir / arch_name
        latest_path.write_text(clean_latest, encoding="utf-8")
        arch_path.write_text(clean_arch, encoding="utf-8")
        # handoffs/ is ignored by jj (conversation text never enters history); old parts are pruned instead
        cutoff = dt.datetime.now().timestamp() - HANDOFF_KEEP_DAYS * 86400
        for old in out_dir.glob("handoff-*-part-*.md"):
            try:
                if old != arch_path and old.stat().st_mtime < cutoff:
                    old.unlink()
            except OSError:
                pass
        sync_index(root)
        return (
            latest_path,
            latest_path.relative_to(root).as_posix(),
            arch_path.relative_to(root).as_posix(),
        )


def _redact_text(text: str) -> str:
    out_lines = []
    for line in (text or "").splitlines():
        if find_secrets(line):
            prefix = re.match(r"^(\s*(?:-\s*)?)", line)
            out_lines.append(f"{prefix.group(1) if prefix else ''}[redacted credential]")
        else:
            out_lines.append(line)
    return "\n".join(out_lines) + "\n"


# --------------------------------------------------------------------------- digests, prompt block & lint


def _query_digest_rows(root: Path, scope: str) -> list[sqlite3.Row]:
    con = _connect_db(root)
    try:
        return con.execute(
            """
            SELECT rel_path, scope, type, title, description, updated
            FROM pages
            WHERE scope = ? AND status = 'active'
            ORDER BY updated DESC, title COLLATE NOCASE ASC
            """,
            (scope,),
        ).fetchall()
    finally:
        con.close()


def prompt_memory_block(workspace: Path, max_chars: int | None = None) -> str:
    """Deterministic compact summary of global preferences + active project memories for Ray's system prompt."""
    root = resolve_memory_root(workspace)
    if root is None:
        return ""
    sync_index(root, backfill_embeddings=False)
    cap = max_chars if max_chars is not None else int(load_config().get("max_digest_chars") or DEFAULT_CAPS["digest_chars"])
    slug = resolve_project_slug(workspace, root, register=False)

    g_rows = _query_digest_rows(root, "global")
    p_rows = _query_digest_rows(root, slug) if slug != "global" else []

    g_prefs = sorted((r for r in g_rows if r["type"] == "preference"), key=lambda r: r["title"].lower())
    g_other = sorted((r for r in g_rows if r["type"] != "preference"), key=lambda r: (-len(r["updated"]), r["title"].lower()))
    p_pages = sorted(
        (r for r in p_rows if not r["rel_path"].startswith("handoffs/")),
        key=lambda r: (0 if r["type"] == "preference" else 1 if r["type"] == "decision" else 2, r["title"].lower()),
    )

    lines: list[str] = []
    used = 0

    def _add_group(header: str, rows: list[sqlite3.Row]) -> None:
        nonlocal used
        if not rows or used + len(header) + 20 > cap:
            return
        lines.append(header)
        used += len(header) + 1
        for i, r in enumerate(rows):
            entry = f"- [{r['title']}]({r['rel_path']}) — {r['description']}".rstrip(" —")
            if used + len(entry) + 45 > cap:
                rem = len(rows) - i
                tail = f"- ... {rem} more: search memory"
                lines.append(tail)
                used += len(tail) + 1
                break
            lines.append(entry)
            used += len(entry) + 1

    _add_group("Global preferences:", g_prefs)
    _add_group(f"Project ({slug}):", p_pages)
    if g_other and used < cap - 200:
        _add_group("Global knowledge:", g_other[:12])

    handoff_latest = root / "handoffs" / slug / "latest.md"
    if handoff_latest.is_file() and used + 80 < cap:
        lines.append(f"Latest handoff: handoffs/{slug}/latest.md")
    return "\n".join(lines)


def build_digest(root: Path, workspace: Path | None = None, max_tokens: int = 1500, compact: bool = False) -> str:
    sync_index(root, backfill_embeddings=False)
    slug = resolve_project_slug(workspace, root, register=False) if workspace else "global"
    g_rows = _query_digest_rows(root, "global")
    p_rows = _query_digest_rows(root, slug) if slug != "global" else []
    total = len(g_rows) + len(p_rows)
    if total == 0:
        return (
            f"Ray Memory (`{root}`): consolidated jj store is ready (project `{slug}`, 0 pages yet). "
            "Save decisions, constraints, and preferences with `memory_write` / `memory_remember`."
        )
    header = [
        f"Ray Memory (`{root}`, active project `{slug}`, {len(g_rows)} global / {len(p_rows)} project pages):",
        "Search before guessing (`memory_search` or `dl_memory.py search <terms>`); read only needed pages.",
    ]
    if compact:
        g_prefs = [r for r in g_rows if r["type"] == "preference"][:10]
        if g_prefs:
            header.append("Global preferences: " + "; ".join(f"{r['title']} ({r['rel_path']})" for r in g_prefs))
        return "\n".join(header)

    budget = max_tokens * 4 - sum(len(x) + 1 for x in header)
    sections = [
        ("Global preferences (always apply)", sorted((r for r in g_rows if r["type"] == "preference"), key=lambda r: r["title"].lower())),
        (f"Project `{slug}` preferences & decisions", sorted((r for r in p_rows if r["type"] in ("preference", "decision") and not r["rel_path"].startswith("handoffs/")), key=lambda r: r["updated"], reverse=True)),
        (f"Project `{slug}` other pages", sorted((r for r in p_rows if r["type"] not in ("preference", "decision") and not r["rel_path"].startswith("handoffs/")), key=lambda r: r["updated"], reverse=True)[:10]),
        ("Global knowledge", sorted((r for r in g_rows if r["type"] != "preference"), key=lambda r: r["updated"], reverse=True)[:10]),
    ]
    out = list(header)
    for title, grp in sections:
        if not grp or budget < 80:
            continue
        block = ["", f"{title}:"]
        used = len(title) + 3
        for i, r in enumerate(grp):
            line = f"- [{r['title']}]({r['rel_path']}) — {r['description']}".rstrip(" —")
            if used + len(line) + 50 > budget:
                block.append(f"- ... {len(grp) - i} more (use search)")
                break
            block.append(line)
            used += len(line) + 1
        out.extend(block)
        budget -= used
    return "\n".join(out)


def lint_repo(root: Path, *, stale_days: int = 90, max_lines: int = 250, auto_fix: bool = False) -> tuple[list[str], list[str], int]:
    """Check frontmatter, ## Sources, relative links, secrets, duplicates, and staleness."""
    today = dt.date.today()
    errors: list[str] = []
    warnings: list[str] = []
    files = list(_iter_memory_files(root))
    inbound: dict[str, int] = {rel: 0 for _, rel in files}
    titles_by_scope: dict[tuple[str, str], list[str]] = {}

    for path, rel in files:
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError) as exc:
            errors.append(f"{rel}:1 unreadable ({exc.__class__.__name__})")
            continue
        lines = text.splitlines()
        meta, meta_err, body_start = parse_frontmatter(lines)
        if meta_err:
            errors.append(f"{rel}:1 {meta_err}")
        else:
            missing = [k for k in REQUIRED_KEYS if meta.get(k) in ("", None)]
            if missing:
                errors.append(f"{rel}:1 frontmatter missing: {', '.join(missing)}")
            if meta.get("type") and meta["type"] not in TYPES:
                errors.append(f"{rel}:1 invalid type {meta['type']!r}")
            if meta.get("status") and meta["status"] not in STATUSES:
                errors.append(f"{rel}:1 invalid status {meta['status']!r}")
            for dk in DATE_KEYS:
                if meta.get(dk) and parse_date(meta[dk]) is None:
                    errors.append(f"{rel}:1 invalid date {dk}={meta[dk]!r}")
            if meta.get("status") == "superseded":
                sup = meta.get("superseded_by")
                if not sup:
                    errors.append(f"{rel}:1 superseded page needs superseded_by")
                elif not (path.parent / sup).exists() and not (root / sup).exists():
                    errors.append(f"{rel}:1 superseded_by target not found: {sup}")
            desc = str(meta.get("description") or "")
            if len(desc) > 150:
                warnings.append(f"{rel}:1 description is {len(desc)} chars (>150)")
            if meta.get("status", "active") == "active" and not rel.startswith("handoffs/"):
                titles_by_scope.setdefault((_scope_from_rel(rel), str(meta.get("title") or "").strip().lower()), []).append(rel)

        if not any(re.match(r"^##\s+Sources\s*$", ln) for _, ln in _body_lines(lines, body_start)):
            errors.append(f"{rel}:1 missing '## Sources' section")

        for n, line in _body_lines(lines, body_start):
            for target in _links_in(line):
                resolved = (path.parent / unquote(target.split("#", 1)[0])).resolve()
                if not resolved.exists():
                    errors.append(f"{rel}:{n} broken link: {target}")
                else:
                    try:
                        dst_rel = resolved.relative_to(root.resolve()).as_posix()
                        if dst_rel in inbound and dst_rel != rel:
                            inbound[dst_rel] += 1
                    except ValueError:
                        pass

        for n, label in find_secrets(text):
            errors.append(f"{rel}:{n} possible credential ({label}) — store in private/.env with `env set`")

        if not KEBAB_MD.match(path.name):
            warnings.append(f"{rel}:1 filename is not kebab-case")
        if len(lines) > max_lines and not rel.startswith("handoffs/"):
            warnings.append(f"{rel}:1 page has {len(lines)} lines (>{max_lines})")
        verified = parse_date(meta.get("last_verified"))
        if verified and meta.get("type") not in NO_STALE_CHECK and meta.get("status", "active") == "active":
            age = (today - verified).days
            if age > stale_days:
                warnings.append(f"{rel}:1 last_verified is {age} days old")

    for (scope, t), rels in titles_by_scope.items():
        if t and len(rels) > 1:
            warnings.append(f"{rels[0]}:1 duplicate title in scope {scope!r}: {', '.join(rels[1:])}")

    if auto_fix:
        with write_lock(root):
            changed = ensure_gitignore(root)
            sync_index(root)
            if changed:
                _approve_paths(root, [".gitignore"], global_ok=False)
                _jj_commit(root, f"{detect_agent()}: lint upkeep (.gitignore)", [".gitignore"])
    return errors, warnings, len(files)


def mv_page(root: Path, src_rel: str, dst_rel: str, agent: str | None = None, *, approved: bool = False) -> str:
    with write_lock(root):
        src = _safe_rel_path(root, src_rel)
        dst = _safe_rel_path(root, dst_rel)
        if src is None or not src.is_file():
            return f"Error: source not found or protected: {src_rel}"
        if dst is None or dst.exists():
            return f"Error: invalid or existing destination: {dst_rel}"
        if not KEBAB_MD.match(dst.name):
            return f"Error: destination filename must be kebab-case: {dst.name}"
        r_src = src.relative_to(root.resolve()).as_posix()
        r_dst = dst.relative_to(root.resolve()).as_posix()
        if (r_src.startswith("global/") or r_dst.startswith("global/")) and not approved:
            return GLOBAL_APPROVAL_MSG
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        _approve_paths(root, [r_src, r_dst], global_ok=True)
        sync_index(root)
        rev = _jj_commit(root, f"{agent or detect_agent()}: mv {r_src} -> {r_dst}", [r_src, r_dst])
        return f"Moved {r_src} → {r_dst}" + (f" (jj {rev})" if rev else "")


def rm_page(root: Path, page_rel: str, agent: str | None = None, *, approved: bool = False) -> str:
    with write_lock(root):
        target = _safe_rel_path(root, page_rel)
        if target is None or not target.is_file():
            return f"Error: page not found or protected: {page_rel}"
        rel = target.relative_to(root.resolve()).as_posix()
        if rel.startswith("global/") and not approved:
            return GLOBAL_APPROVAL_MSG
        target.unlink()
        _approve_paths(root, [rel], global_ok=True)        # a missing file: its approval record is dropped
        sync_index(root)
        rev = _jj_commit(root, f"{agent or detect_agent()}: remove {rel}", [rel])
        return f"Removed {rel} (recoverable with `memory undo`)" + (f" (jj {rev})" if rev else "")


# --------------------------------------------------------------------------- credentials (private/.env)


ENV_LINE_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")
ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
ENV_HEADER = (
    "# Ray Memory credentials — private, gitignored, never committed to jj.\n"
    "# Agents: never open this file directly. Use `env get KEY --approved` after user approval.\n"
)


def _env_quote(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_@%+=:,./~^-]*", value):
        return value
    if "'" not in value and "\n" not in value:
        return f"'{value}'"
    esc = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("$", "\\$")
    return f'"{esc}"'


def _env_unquote(raw: str) -> str:
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] == "'":
        return raw[1:-1]
    if len(raw) >= 2 and raw[0] == raw[-1] == '"':
        return re.sub(r"\\(.)", lambda m: "\n" if m.group(1) == "n" else m.group(1), raw[1:-1])
    return re.sub(r"\s+#.*$", "", raw)


def _env_entries(lines: list[str]) -> dict[str, tuple[int, str]]:
    entries: dict[str, tuple[int, str]] = {}
    for i, line in enumerate(lines):
        m = ENV_LINE_RE.match(line)
        if m:
            note = lines[i - 1].lstrip("# ").strip() if i and lines[i - 1].startswith("#") else ""
            entries[m.group(1)] = (i, note)
    return entries


def env_cmd(
    root: Path,
    action: str,
    key: str = "",
    value: str | None = None,
    *,
    note: str | None = None,
    approved: bool = False,
) -> tuple[int, str]:
    path = root / ENV_REL
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    entries = _env_entries(lines)

    if action == "list":
        if not entries:
            return 0, f"No credentials stored yet ({ENV_REL})."
        return 0, "\n".join(f"{k}" + (f" — {n}" if n else "") for k, (_, n) in sorted(entries.items()))

    if not key or not ENV_KEY_RE.match(key):
        return 2, "Error: KEY must contain only letters, digits, and underscores (e.g. GITHUB_TOKEN)."

    if action == "get":
        if not approved:
            return 3, f"Approval needed: ask the user before reading {key}, then run with --approved."
        if key not in entries:
            return 1, f"Error: {key} is not in {ENV_REL}."
        return 0, _env_unquote(ENV_LINE_RE.match(lines[entries[key][0]]).group(2))

    if action == "rm":
        if key not in entries:
            return 1, f"Error: {key} is not in {ENV_REL}."
        idx, old_note = entries[key]
        del lines[idx]
        if old_note and idx and lines[idx - 1].startswith("#"):
            del lines[idx - 1]
        path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        return 0, f"Removed {key} from {ENV_REL}."

    # set
    val = sys.stdin.read().rstrip("\n") if value in (None, "-") else value
    today = dt.date.today().isoformat()
    note_line = f"{note} ({today})" if note else None
    entry = f"{key}={_env_quote(val)}"
    if key in entries:
        idx, old_note = entries[key]
        lines[idx] = entry
        if note_line:
            if old_note and idx and lines[idx - 1].startswith("#"):
                lines[idx - 1] = f"# {note_line}"
            else:
                lines.insert(idx, f"# {note_line}")
    else:
        if not lines:
            lines = ENV_HEADER.rstrip("\n").split("\n")
        lines += ["", f"# {note_line or key}", entry]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return 0, f"Saved {key} to {ENV_REL}."


# --------------------------------------------------------------------------- unified tool & MCP server


def handle_memory_action(args: dict[str, Any], workspace: Path | None = None, mode: str = "act",
                         approved: bool = False) -> str:
    """One entry point for Ray's `memory` tool, the MCP tools and the slash commands.  approved=True only when the
    caller got the user's yes for a global/ change (Ray's card, an MCP tool behind the harness's prompt)."""
    action = (args.get("action") or "").strip().lower()
    alias_map = {"read_page": "read", "new_page": "write", "log": "remember"}
    args = dict(args)
    if not args.get("path") and args.get("page_path"):
        args["path"] = args["page_path"]
    action = alias_map.get(action, action)
    if not action:
        return "Error: action required (search, read, write, remember, digest, history, diff, undo, lint, projects, env_list)"

    mutating = {"write", "update", "remember", "undo", "mv", "rm", "init", "backup"}
    if mode == "plan" and action in mutating:
        return f"Error: [PLAN MODE] Action '{action}' modifies memory and is disabled in Plan Mode."

    root = resolve_memory_root(workspace, require_exists=False)
    if root is None:
        return "Error: consolidated memory is disabled (RAY_MEMORY_DIR=off) or unconfigured (~/.config/dl-ai/memory.json)."
    if action == "init":
        init_repo(root)
        return f"Consolidated memory ready at {root}"
    if not root.is_dir():
        return f"Error: memory store does not exist at {root}. Run `init` first."

    if action == "search":
        q = (args.get("query") or args.get("terms") or "").strip()
        if not q:
            return "Error: query required for search."
        hits = search(root, q, scope=args.get("scope") or "auto", workspace=workspace, limit=int(args.get("limit") or 8))
        return format_search_results(hits, q)
    if action == "read":
        p = args.get("path") or args.get("page_path") or args.get("query") or ""
        return read_page(root, p, workspace=workspace)
    if action in ("write", "update"):
        ptype = args.get("page_type") or "decision"
        slug = args.get("slug") or ""
        title = args.get("title") or ""
        desc = args.get("description") or ""
        content = args.get("content") or args.get("summary") or ""
        if not (slug and title):
            return "Error: slug and title are required for write."
        if not desc:
            desc = (content.splitlines()[0] if content else title)[:140]
        return write_page(
            root,
            page_type=ptype,
            slug=slug,
            title=title,
            description=desc,
            content=content,
            tags=args.get("tags"),
            scope=args.get("scope") or "auto",
            workspace=workspace,
            mode="upsert",
            approved=approved,
        )
    if action == "remember":
        fact = args.get("content") or args.get("summary") or args.get("query") or args.get("fact") or ""
        return remember(root, fact, workspace=workspace, scope=args.get("scope") or "auto", approved=approved)
    if action == "digest":
        return build_digest(root, workspace, max_tokens=int(args.get("max_tokens") or 1500))
    if action == "history":
        return jj_history(root, scope=args.get("scope"), workspace=workspace, limit=int(args.get("limit") or 15))
    if action == "diff":
        return jj_diff(root, rev=args.get("rev") or "@-")
    if action == "undo":
        return jj_undo(root, rev=args.get("rev") or "@-", approved=approved)
    if action == "lint":
        errors, warnings, count = lint_repo(root, auto_fix=True)
        lines = [f"ERROR {e}" for e in errors] + [f"WARN {w}" for w in warnings]
        lines.append(f"{len(errors)} error(s), {len(warnings)} warning(s), {count} page(s) checked")
        return "\n".join(lines)
    if action == "projects":
        projs = list_projects(root)
        if not projs:
            return "No registered projects yet."
        return "\n".join(f"- {p['slug']} ({p['pages']} pages) -> {', '.join(p['paths']) or '(unmapped)'}" for p in projs)
    if action == "env_list":
        _, out = env_cmd(root, "list")
        return out
    return f"Error: unknown memory action {action!r}"


MCP_TOOLS = [
    {
        "name": "memory_search",
        "description": "Search consolidated Ray/Claude/Antigravity long-term memory across global preferences and all projects (SQLite FTS5 + Model2Vec semantic search).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search terms or natural language question."},
                "scope": {"type": "string", "enum": ["auto", "global", "project", "all"], "default": "auto"},
                "workspace": {"type": "string", "description": "Optional active project directory path for project scoping."},
                "limit": {"type": "integer", "default": 8},
            },
            "required": ["query"],
        },
    },
    {
        "name": "memory_read",
        "description": "Read a full Markdown page from the consolidated memory store.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative memory path (e.g. 'global/preferences/ac.md' or 'projects/strata/decisions/x.md')."},
                "workspace": {"type": "string"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "memory_write",
        "description": "Create or update a page in the current project's memory (secret-scanned, indexed, committed in jj). For a rule that applies in every project, use memory_write_global instead.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace": {"type": "string", "description": "The project's directory (default: the server's working directory)."},
                "page_type": {"type": "string", "enum": ["decision", "concept", "entity", "preference", "artifact", "log"]},
                "slug": {"type": "string"},
                "title": {"type": "string"},
                "description": {"type": "string"},
                "content": {"type": "string"},
                "tags": {"type": "string"},
            },
            "required": ["page_type", "slug", "title", "description", "content"],
        },
    },
    {
        "name": "memory_write_global",
        "description": "Create or update a global/ page: a household, OS or cross-project rule that every agent sees in every project. Only call this after the user asked for it; the user approves each call.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "page_type": {"type": "string", "enum": ["decision", "concept", "entity", "preference", "artifact", "log"]},
                "slug": {"type": "string"},
                "title": {"type": "string"},
                "description": {"type": "string"},
                "content": {"type": "string"},
                "tags": {"type": "string"},
            },
            "required": ["page_type", "slug", "title", "description", "content"],
        },
    },
    {
        "name": "memory_remember",
        "description": "Quickly save a short preference, decision, or constraint to the current project's memory (global rules: memory_write_global).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "fact": {"type": "string"},
                "workspace": {"type": "string", "description": "The project's directory (default: the server's working directory)."},
            },
            "required": ["fact"],
        },
    },
    {
        "name": "memory_history",
        "description": "Show recent jj memory commits (change ID, commit ID, age, description).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "scope": {"type": "string", "enum": ["all", "global", "project"]},
                "workspace": {"type": "string"},
                "limit": {"type": "integer", "default": 15},
            },
        },
    },
    {
        "name": "memory_diff",
        "description": "Inspect the jj diff of a memory revision (default '@-').",
        "inputSchema": {
            "type": "object",
            "properties": {"rev": {"type": "string", "default": "@-"}},
        },
    },
    {
        "name": "memory_undo",
        "description": "Revert one memory commit with jj revert (a commit that touched global/ can only be reverted from Ray or a terminal).",
        "inputSchema": {
            "type": "object",
            "properties": {"rev": {"type": "string", "default": "@-"}},
        },
    },
    {
        "name": "memory_lint",
        "description": "Validate all memory pages (frontmatter, links, sources, secrets) and re-sync the index.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "memory_projects",
        "description": "List all projects registered in the consolidated memory store and their workspace paths.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "memory_env_list",
        "description": "List credential key names stored in private/.env (never prints values).",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def _default_workspace() -> Path | None:
    """The MCP server's working directory is the client's project folder; $HOME or / is no project."""
    cwd = Path.cwd().resolve()
    return None if cwd in (Path.home().resolve(), Path("/")) else cwd


def _mcp_call(name: str, args: dict[str, Any]) -> str:
    ws = Path(args["workspace"]).expanduser() if args.get("workspace") else _default_workspace()
    if name in ("memory_write", "memory_write_global", "memory_remember"):
        args = {k: v for k, v in args.items() if k != "scope"}       # a write's scope comes from the tool's name
    if name == "memory_write_global":
        return handle_memory_action({"action": "write", **args, "scope": "global"}, workspace=ws, approved=True)
    mapping = {
        "memory_search": {"action": "search", **args},
        "memory_read": {"action": "read", **args},
        "memory_write": {"action": "write", **args, "scope": "project"},
        "memory_remember": {"action": "remember", **args, "scope": "project"},
        "memory_history": {"action": "history", **args},
        "memory_diff": {"action": "diff", **args},
        "memory_undo": {"action": "undo", **args},
        "memory_lint": {"action": "lint", **args},
        "memory_projects": {"action": "projects", **args},
        "memory_env_list": {"action": "env_list", **args},
    }
    if name not in mapping:
        return f"Error: unknown tool {name}"
    return handle_memory_action(mapping[name], workspace=ws, mode="act")


def run_mcp_server() -> int:
    """Newline-delimited JSON-RPC 2.0 stdio MCP server shared by Claude Code and Antigravity."""
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        try:
            req = json.loads(line)
        except ValueError:
            continue
        method = req.get("method")
        msg_id = req.get("id")
        if msg_id is None:
            continue
        if method == "ping":
            res: dict[str, Any] = {"jsonrpc": "2.0", "id": msg_id, "result": {}}
        elif method == "initialize":
            proto = str((req.get("params") or {}).get("protocolVersion") or "2024-11-05")
            res = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": proto,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "ray-memory", "version": "1.0.0"},
                },
            }
        elif method == "tools/list":
            res = {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": MCP_TOOLS}}
        elif method == "tools/call":
            params = req.get("params") or {}
            name = str(params.get("name") or "")
            t_args = params.get("arguments") or {}
            try:
                text = _mcp_call(name, t_args if isinstance(t_args, dict) else {})
                is_err = text.startswith("Error:")
            except Exception as exc:
                text = f"Error: {type(exc).__name__}: {exc}"
                is_err = True
            res = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {"content": [{"type": "text", "text": text}], "isError": is_err},
            }
        else:
            res = {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}
        sys.stdout.write(json.dumps(res) + "\n")
        sys.stdout.flush()
    return 0


# --------------------------------------------------------------------------- unified hooks (Claude Code & Antigravity)


class _HookState:
    def __init__(self, session_id: str):
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id or "unknown")
        self.path = CACHE_DIR / "state" / f"{safe}.json"
        try:
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.data = {}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data), encoding="utf-8")
        tmp.replace(self.path)


def _snapshot_tree(root: Path) -> dict[str, int]:
    return {rel: int(p.stat().st_mtime_ns) for p, rel in _iter_memory_files(root) if p.is_file()}


def _upkeep_direct_edits(root: Path, state: _HookState, agent: str) -> str | None:
    before = state.data.get("snapshot")
    after = _snapshot_tree(root)
    if before is None:
        state.data["snapshot"] = after
        return None
    touched = sorted(
        [r for r in after if r not in before or after[r] != before[r]]
        + [r for r in before if r not in after]
    )
    if not touched:
        return None
    with write_lock(root):
        take_guard_reports()
        guarded = _guard_working_copy(root)          # secrets and unapproved global/ edits: quarantined here
        take_guard_reports()
        sync_index(root, backfill_embeddings=False)
        errors, _, _ = lint_repo(root, auto_fix=False)
        bad = {e.split(":", 1)[0] for e in errors}
        mine = [e for e in errors if e.split(":", 1)[0] in set(touched)]
        clean = [r for r in touched if r not in bad and not r.startswith("handoffs/")]
        if clean:
            _jj_commit(root, f"{agent}: update {', '.join(clean[:3])}" + ("..." if len(clean) > 3 else ""), clean)
    state.data["snapshot"] = _snapshot_tree(root)
    state.data["edits_outside"] = 0
    parts = []
    if guarded:
        parts.append("Ray Memory refused these edits (store credentials with `dl_memory.py env set`; change global/ "
                     "only with the memory_write_global tool, and only when the user asked):\n" + "\n".join(f"- {g}" for g in guarded))
    if mine:
        parts.append("Ray Memory lint found errors in pages you just changed; they are not committed until fixed:\n"
                     + "\n".join(f"- {e}" for e in mine[:10]))
    return "\n\n".join(parts) or None


def _reads_private_env(tool: str, tool_input: dict[str, Any], root: Path) -> bool:
    priv_dir = (root / PRIVATE_DIR).resolve()
    env_file = (root / ENV_REL).resolve()
    if tool in ("Read", "Grep", "Glob", "view_file"):
        raw = str(tool_input.get("file_path") or tool_input.get("path") or tool_input.get("AbsolutePath") or "")
        if not raw:
            return False
        try:
            cand = Path(raw).expanduser().resolve()
            return cand == env_file or cand == priv_dir or cand.is_relative_to(priv_dir)
        except OSError:
            return False
    if tool in ("Bash", "run_command"):
        cmd = str(tool_input.get("command") or tool_input.get("CommandLine") or "")
        return bool(re.search(r"private/\.env\b", cmd)) and "dl_memory.py" not in cmd
    return False


def _inside_dir(path_str: str | None, root: Path) -> bool:
    if not path_str:
        return False
    try:
        return Path(path_str).expanduser().resolve().is_relative_to(root.resolve())
    except (OSError, ValueError):
        return False


def handle_hook(harness: str, event: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    root = resolve_memory_root()
    neutral = {"decision": "allow"} if (harness == "antigravity" and event == "Stop") else ({} if harness == "antigravity" else None)
    if root is None:
        return neutral

    edit_tools = {"Write", "Edit", "MultiEdit", "NotebookEdit", "write_to_file", "replace_file_content", "multi_replace_file_content"}
    nudge_msg = (
        "Ray Memory capture check: this task changed several files and nothing was saved to consolidated memory. "
        "If it produced a reusable decision, constraint, gotcha, or preference worth keeping, save it now with "
        "`memory_write` / `memory_remember` and mention it in one line. Otherwise stop without comment."
    )

    if harness == "claude":
        ev = str(payload.get("hook_event_name") or event or "")
        ws = Path(payload["cwd"]).expanduser() if payload.get("cwd") else None
        state = _HookState(str(payload.get("session_id") or "claude"))
        tool = str(payload.get("tool_name") or "")
        tin = payload.get("tool_input") or {}
        fpath = tin.get("file_path") or tin.get("notebook_path")
        out = None

        if ev == "SessionStart":
            state.data["snapshot"] = _snapshot_tree(root)
            out = {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": build_digest(root, ws, 1500)}}
        elif ev == "PreToolUse":
            if _reads_private_env(tool, tin, root):
                out = {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": "Ray Memory: do not open private/.env directly. Ask the user for approval, then run `dl_memory.py env get KEY --approved`.",
                    }
                }
            elif tool in edit_tools and fpath and _inside_dir(fpath, root / "global"):
                out = {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": ("Ray Memory: global/ pages reach every agent in every project, so they "
                                                     "change only through the memory_write_global tool, which asks the "
                                                     "user. Use it (or memory_write for this project) instead."),
                    }
                }
            elif fpath and _inside_dir(fpath, root) and not _inside_dir(fpath, root / PRIVATE_DIR):
                txt ="\n".join(filter(None, [tin.get("content"), tin.get("new_string"), *[e.get("new_string") for e in tin.get("edits") or []]]))
                err = secret_error(txt, fpath)
                if err:
                    out = {
                        "hookSpecificOutput": {
                            "hookEventName": "PreToolUse",
                            "permissionDecision": "deny",
                            "permissionDecisionReason": f"Ray Memory: {err}",
                        }
                    }
        elif ev == "PostToolUse":
            if tool in edit_tools and not _inside_dir(fpath, root):
                state.data["edits_outside"] = state.data.get("edits_outside", 0) + 1
            msg = _upkeep_direct_edits(root, state, "Claude Code")
            if msg:
                out = {"decision": "block", "reason": msg}
        elif ev == "Stop":
            msg = _upkeep_direct_edits(root, state, "Claude Code")
            if msg:
                out = {"decision": "block", "reason": msg}
            elif not payload.get("stop_hook_active") and state.data.get("edits_outside", 0) >= DEFAULT_CAPS["nudge_edits"]:
                state.data["edits_outside"] = 0
                out = {"decision": "block", "reason": nudge_msg}
        state.save()
        return out

    # Antigravity hook
    ws_paths = payload.get("workspacePaths") or []
    ws = Path(ws_paths[0]).expanduser() if ws_paths else None
    state = _HookState(str(payload.get("conversationId") or "antigravity"))
    call = payload.get("toolCall") or {}
    args = call.get("args") or {}
    out: dict[str, Any] = neutral  # type: ignore[assignment]

    if event == "PreInvocation":
        steps: list[dict[str, str]] = []
        if not state.data.get("started"):
            state.data["started"] = True
            state.data["snapshot"] = _snapshot_tree(root)
            steps.append({"ephemeralMessage": build_digest(root, ws, 1500)})
        elif payload.get("invocationNum") == 0:
            steps.append({"ephemeralMessage": build_digest(root, ws, 400, compact=True)})
        msg = _upkeep_direct_edits(root, state, "Antigravity")
        pending = state.data.get("pending", []) + ([msg] if msg else [])
        steps.extend({"ephemeralMessage": m} for m in pending)
        state.data["pending"] = []
        if steps:
            out = {"injectSteps": steps}
    elif event == "PostToolUse":
        tname = str(call.get("name") or "write_to_file")
        target = args.get("TargetFile") or args.get("AbsolutePath")
        if tname in edit_tools and not _inside_dir(target, root):
            state.data["edits_outside"] = state.data.get("edits_outside", 0) + 1
        msg = _upkeep_direct_edits(root, state, "Antigravity")
        if msg:
            state.data["pending"] = state.data.get("pending", []) + [msg]
    elif event == "Stop":
        msg = _upkeep_direct_edits(root, state, "Antigravity")
        pending = state.data.get("pending", []) + ([msg] if msg else [])
        if pending:
            state.data["pending"] = []
            out = {"decision": "continue", "reason": "\n\n".join(pending)}
        elif state.data.get("edits_outside", 0) >= DEFAULT_CAPS["nudge_edits"]:
            state.data["edits_outside"] = 0
            out = {"decision": "continue", "reason": nudge_msg}
    state.save()
    return out


# --------------------------------------------------------------------------- CLI


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", type=Path, help="override memory root")
    common.add_argument("--workspace", "-w", type=Path, help="active project workspace path")
    common.add_argument("--agent", help="agent attribution for jj commits")

    ap = argparse.ArgumentParser(description="Consolidated jj + SQLite FTS5 + Model2Vec memory CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", parents=[common], help="initialize consolidated jj memory store")

    p = sub.add_parser("search", parents=[common], help="hybrid FTS5 + semantic search")
    p.add_argument("terms", nargs="+")
    p.add_argument("--scope", choices=["auto", "global", "project", "all"], default="auto")
    p.add_argument("--limit", type=int, default=8)

    p = sub.add_parser("read", parents=[common], help="read a memory page")
    p.add_argument("path")

    p = sub.add_parser("write", parents=[common], help="create or update a memory page")
    p.add_argument("type", choices=sorted(FOLDERS))
    p.add_argument("slug")
    p.add_argument("--title", required=True)
    p.add_argument("--description", required=True)
    p.add_argument("--content", default="")
    p.add_argument("--tags", default="")
    p.add_argument("--scope", choices=["auto", "global", "project"], default="auto")
    p.add_argument("--mode", choices=["create", "upsert", "append"], default="upsert")
    p.add_argument("--force", action="store_true")

    p = sub.add_parser("remember", parents=[common], help="save a preference or rule")
    p.add_argument("fact", nargs="+")
    p.add_argument("--scope", choices=["auto", "global", "project"], default="auto")

    p = sub.add_parser("digest", parents=[common], help="print session-start memory digest")
    p.add_argument("--max-tokens", type=int, default=1500)
    p.add_argument("--compact", action="store_true")

    p = sub.add_parser("history", parents=[common], help="show recent jj memory commits")
    p.add_argument("--scope", choices=["all", "global", "project"], default="all")
    p.add_argument("--limit", type=int, default=15)

    p = sub.add_parser("diff", parents=[common], help="show jj diff of a memory commit")
    p.add_argument("rev", nargs="?", default="@-")

    p = sub.add_parser("undo", parents=[common], help="revert a memory commit cleanly via jj")
    p.add_argument("rev", nargs="?", default="@-")

    p = sub.add_parser("lint", parents=[common], help="validate pages and re-sync SQLite index")
    p.add_argument("--fix", action="store_true")

    sub.add_parser("projects", parents=[common], help="list registered projects")
    sub.add_parser("sync", parents=[common], help="sync SQLite index from disk")

    p = sub.add_parser("mv", parents=[common], help="move/rename a page")
    p.add_argument("src")
    p.add_argument("dst")

    p = sub.add_parser("rm", parents=[common], help="remove a page")
    p.add_argument("page")

    p = sub.add_parser("env", parents=[common], help="credentials in private/.env")
    p.add_argument("action", choices=["set", "get", "list", "rm"])
    p.add_argument("key", nargs="?", default="")
    p.add_argument("value", nargs="?")
    p.add_argument("--note")
    p.add_argument("--approved", action="store_true")

    sub.add_parser("scan-secrets", help="scan stdin for credentials")
    sub.add_parser("mcp", help="run stdio MCP server")

    p = sub.add_parser("hook", help="run Claude Code or Antigravity lifecycle hook")
    p.add_argument("harness", choices=["claude", "antigravity"])
    p.add_argument("event", nargs="?", default="")
    return ap


def _tty_yes(question: str) -> bool:
    """Ask on the controlling terminal, not stdin: an agent's shell has none, so it cannot answer for the user."""
    try:
        with open("/dev/tty", "r+", encoding="utf-8") as tty:
            tty.write(f"{question} [y/N] ")
            tty.flush()
            return tty.readline().strip().lower() in ("y", "yes", "d", "da")
    except OSError:
        return False


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "scan-secrets":
        hits = find_secrets(sys.stdin.read())
        for n, lbl in hits:
            print(f"line {n}: possible secret ({lbl})")
        return 1 if hits else 0
    if args.cmd == "mcp":
        return run_mcp_server()
    if args.cmd == "hook":
        try:
            raw = sys.stdin.read()
            payload = json.loads(raw) if raw.strip() else {}
            out = handle_hook(args.harness, args.event, payload)
        except Exception:
            try:
                CACHE_DIR.mkdir(parents=True, exist_ok=True)
                with open(CACHE_DIR / "hook-errors.log", "a", encoding="utf-8") as fh:
                    fh.write(f"--- {dt.datetime.now().isoformat()} {args.harness} {args.event}\n{traceback.format_exc()}\n")
            except OSError:
                pass
            out = {"decision": "allow"} if (args.harness == "antigravity" and args.event == "Stop") else ({} if args.harness == "antigravity" else None)
        if out is not None:
            print(json.dumps(out))
        return 0

    root = args.root.expanduser().resolve() if args.root else resolve_memory_root(require_exists=(args.cmd != "init"))
    if args.cmd == "init":
        if root is None:
            print("Error: pass --root or set RAY_MEMORY_DIR / ~/.config/dl-ai/memory.json", file=sys.stderr)
            return 2
        init_repo(root)
        print(f"Initialized consolidated jj memory at {root}")
        return 0
    if root is None:
        print("Error: consolidated memory root not found.", file=sys.stderr)
        return 2

    ws = args.workspace.expanduser().resolve() if args.workspace else _default_workspace()
    if args.cmd == "search":
        q = " ".join(args.terms)
        print(format_search_results(search(root, q, scope=args.scope, workspace=ws, limit=args.limit), q))
        return 0
    if args.cmd == "read":
        out = read_page(root, args.path, workspace=ws)
        print(out)
        return 1 if out.startswith("Error:") else 0
    if args.cmd == "write":
        out = write_page(
            root, page_type=args.type, slug=args.slug, title=args.title, description=args.description,
            content=args.content, tags=args.tags, scope=args.scope, workspace=ws, mode=args.mode,
            agent=args.agent, force=args.force,
            approved=args.scope == "global" and _tty_yes(f"Write global/{FOLDERS[args.type]}/{args.slug}.md for every agent?"),
        )
        print(out)
        return 1 if out.startswith("Error:") else 0
    if args.cmd == "remember":
        fact = " ".join(args.fact)
        glob = args.scope == "global" or fact.lower().startswith(("global ", "global:"))
        out = remember(root, fact, workspace=ws, scope=args.scope, agent=args.agent,
                       approved=glob and _tty_yes(f"Save to global/ for every agent: {fact[:80]!r}?"))
        print(out)
        return 1 if out.startswith("Error:") else 0
    if args.cmd == "digest":
        print(build_digest(root, ws, max_tokens=args.max_tokens, compact=args.compact))
        return 0
    if args.cmd == "history":
        print(jj_history(root, scope=args.scope, workspace=ws, limit=args.limit))
        return 0
    if args.cmd == "diff":
        print(jj_diff(root, rev=args.rev))
        return 0
    if args.cmd == "undo":
        out = jj_undo(root, rev=args.rev, agent=args.agent)
        if out == GLOBAL_APPROVAL_MSG and _tty_yes(f"Revert {args.rev}, which changed global/ pages?"):
            out = jj_undo(root, rev=args.rev, agent=args.agent, approved=True)
        print(out)
        return 1 if out.startswith("Error:") else 0
    if args.cmd == "lint":
        errors, warnings, count = lint_repo(root, auto_fix=args.fix)
        for e in errors:
            print(f"ERROR {e}")
        for w in warnings:
            print(f"WARN {w}")
        print(f"{len(errors)} error(s), {len(warnings)} warning(s), {count} page(s) checked")
        return 1 if errors else 0
    if args.cmd == "projects":
        print(handle_memory_action({"action": "projects"}, workspace=ws))
        return 0
    if args.cmd == "sync":
        st = sync_index(root)
        print(f"Synced: {st['indexed']} updated, {st['backfilled']} embedded, {st['removed']} removed, {st['total']} total")
        return 0
    if args.cmd == "mv":
        out = mv_page(root, args.src, args.dst, agent=args.agent)
        if out == GLOBAL_APPROVAL_MSG and _tty_yes(f"Move {args.src} -> {args.dst} (global/)?"):
            out = mv_page(root, args.src, args.dst, agent=args.agent, approved=True)
        print(out)
        return 1 if out.startswith("Error:") else 0
    if args.cmd == "rm":
        out = rm_page(root, args.page, agent=args.agent)
        if out == GLOBAL_APPROVAL_MSG and _tty_yes(f"Remove {args.page} (global/)?"):
            out = rm_page(root, args.page, agent=args.agent, approved=True)
        print(out)
        return 1 if out.startswith("Error:") else 0
    if args.cmd == "env":
        rc, out = env_cmd(root, args.action, args.key, args.value, note=args.note, approved=args.approved)
        print(out)
        return rc
    return 1


if __name__ == "__main__":
    sys.exit(main())
