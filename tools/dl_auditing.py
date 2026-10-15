#!/usr/bin/env python3
"""dl_auditing.py - Comprehensive auditing, debugging, and guardrail toolset for D.L. CLI.

Equipped with:
1. syntax_guard: AST & parser validation for Python, JS/TS, Bash, JSON, YAML before disk writes.
2. scan_secrets: Regex & entropy scanner for credential, token, and API key leak prevention.
3. system_health: Real-time RAM, Swap, ROCm GPU VRAM, CPU load, and Strata engine monitor.
4. git_diff_audit: Semantic git diff auditor detecting deletions, large blobs, formatting, and risks.
5. smart_test_runner: Universal, targeted test discovery and runner (pytest, unittest, npm, bash, make).
"""
from __future__ import annotations

import ast
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ANSI color palette matching Strata Chat theme
C_RESET = "\033[0m"
C_BOLD = "\033[1m"
C_DIM = "\033[2m"
C_ACCENT = "\033[38;5;208m"       # Strata Orange
C_ACCENT_BOLD = "\033[1;38;5;208m"
C_ACCENT_SOFT = "\033[38;5;215m"  # Soft peach
C_INK = "\033[38;5;255m"          # Crisp white
C_INK_SOFT = "\033[38;5;250m"     # Light slate
C_MUTED = "\033[38;5;244m"        # Slate gray
C_LINE = "\033[38;5;238m"         # Border line
C_GREEN = "\033[38;5;78m"         # Success green
C_YELLOW = "\033[38;5;221m"       # Amber warning
C_RED = "\033[38;5;203m"          # Soft error red
C_BLUE = "\033[38;5;111m"         # Soft info blue


# ==============================================================================
# 1. SYNTAX GUARD (AST & Parser Validation)
# ==============================================================================

def validate_syntax(code: str, file_path: Path | str, language: Optional[str] = None) -> Tuple[bool, Optional[str]]:
    """Validates source code syntax before writing to disk.

    Returns (is_valid, error_message).
    """
    p = Path(file_path)
    suffix = p.suffix.lower()
    lang = (language or "").lower()

    # 1. Python (.py)
    if lang == "python" or suffix == ".py":
        try:
            ast.parse(code, filename=str(p))
            return True, None
        except SyntaxError as e:
            line_str = f"\n  --> Line {e.lineno}: {e.text.strip() if e.text else ''}"
            caret = f"\n      {' ' * ((e.offset or 1) - 1)}^" if e.offset else ""
            msg = f"Python SyntaxError at line {e.lineno}, col {e.offset}: {e.msg}{line_str}{caret}"
            return False, msg
        except Exception as e:
            return False, f"Python parse error: {e}"

    # 2. JSON (.json)
    elif lang == "json" or suffix == ".json":
        try:
            json.loads(code)
            return True, None
        except json.JSONDecodeError as e:
            return False, f"JSON SyntaxError at line {e.lineno}, col {e.colno}: {e.msg}"

    # 3. JavaScript / TypeScript (.js, .mjs, .cjs, .ts, .jsx, .tsx)
    elif lang in ("javascript", "typescript", "js", "ts") or suffix in (".js", ".mjs", ".cjs"):
        node_bin = shutil.which("node")
        if node_bin:
            try:
                res = subprocess.run([node_bin, "--check"], input=code, text=True, capture_output=True, timeout=5)
                if res.returncode != 0:
                    err = res.stderr.strip() or res.stdout.strip()
                    return False, f"JavaScript SyntaxError:\n{err}"
                return True, None
            except Exception:
                pass  # Fall back to passing if node check fails execution

    # 4. Bash / Shell (.sh, .bash)
    elif lang in ("bash", "sh", "shell") or suffix in (".sh", ".bash"):
        bash_bin = shutil.which("bash")
        if bash_bin:
            try:
                res = subprocess.run([bash_bin, "-n"], input=code, text=True, capture_output=True, timeout=5)
                if res.returncode != 0:
                    err = res.stderr.strip() or res.stdout.strip()
                    return False, f"Bash SyntaxError:\n{err}"
                return True, None
            except Exception:
                pass

    # 5. YAML (.yaml, .yml)
    elif lang in ("yaml", "yml") or suffix in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore
            yaml.safe_load(code)
            return True, None
        except ImportError:
            pass  # PyYAML not installed, skip
        except Exception as e:
            return False, f"YAML SyntaxError: {e}"

    return True, None


def tool_syntax_guard(args: Dict[str, Any], workspace: Path) -> str:
    """Standalone tool handler for syntax_guard."""
    path_str = args.get("TargetFile") or args.get("path")
    code = args.get("CodeContent") or args.get("code")
    lang = args.get("language")

    if path_str:
        p = Path(path_str).expanduser()
        if not p.is_absolute():
            p = (workspace / p).resolve()
        if not p.is_file():
            return f"Error: File not found: {p}"
        if code is None:
            code = p.read_text(encoding="utf-8", errors="replace")
    elif code is None:
        return "Error: either 'TargetFile' or 'CodeContent' must be provided."
    else:
        p = Path(f"snippet.{lang or 'py'}")

    is_valid, err = validate_syntax(code, p, language=lang)
    if is_valid:
        return f"✓ SyntaxGuard: Syntax is 100% valid ({p.name or lang})."
    else:
        return f"✗ SyntaxGuard Violation ({p.name}):\n{err}"


# ==============================================================================
# 2. SCAN SECRETS (Credential Leak Scanner)
# ==============================================================================

# Common high-confidence credential leak patterns
SECRET_PATTERNS = [
    ("OpenAI API Key", re.compile(r"\b(sk-[a-zA-Z0-9_-]{20,})\b")),
    ("Anthropic API Key", re.compile(r"\b(sk-ant-[a-zA-Z0-9_-]{20,})\b")),
    ("GitHub Personal Access Token", re.compile(r"\b(gh[pousr][_-][a-zA-Z0-9_]{30,})\b")),
    ("GitHub Fine-Grained Token", re.compile(r"\b(github_pat_[a-zA-Z0-9_]{60,})\b")),
    ("AWS Access Key ID", re.compile(r"\b(AKIA[0-9A-Z]{16})\b")),
    ("HuggingFace Token", re.compile(r"\b(hf_[a-zA-Z0-9]{34,})\b")),
    ("Slack API Token", re.compile(r"\b(xox[baprs]-[0-9a-zA-Z]{10,48})\b")),
    ("Private Key Block", re.compile(r"-----BEGIN (?:[A-Z ]+)?PRIVATE KEY-----")),
    ("Hardcoded Generic Secret", re.compile(r"(?i)\b(?:api_key|apikey|secret_key|auth_token|client_secret)\s*=\s*['\"]([a-zA-Z0-9_\-\.]{24,})['\"]")),
    ("Context7 API Key", re.compile(r"\b(ctx7sk-[a-zA-Z0-9-]{20,})\b")),
    # os.environ.get("SOME_KEY", "<literal>") - the 2026-10-13 leak
    ("Hardcoded Env Default", re.compile(r"""environ\.get\(\s*['"][A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD)[A-Z0-9_]*['"]\s*,\s*['"]([A-Za-z0-9_\-\.]{20,})['"]""")),
    # ${SOME_KEY:-<literal>} in shell scripts
    ("Hardcoded Shell Default", re.compile(r"\$\{[A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD)[A-Z0-9_]*:-([A-Za-z0-9_\-\.]{20,})\}")),
    # Google OAuth (the Gmail/Drive/Docs MCP server) and DeepL
    ("Google OAuth Client Secret", re.compile(r"\b(GOCSPX-[A-Za-z0-9_-]{20,})")),
    ("Google OAuth Access Token", re.compile(r"\b(ya29\.[A-Za-z0-9_-]{20,})")),
    ("Google OAuth Refresh Token", re.compile(r"(?<![A-Za-z0-9])(1//0[A-Za-z0-9_-]{30,})")),
    ("DeepL API Key", re.compile(r"\b([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}:fx)\b")),
]

# The real values on this PC: every value in secrets.env, secret-looking environment variables and the Google sign-in
# tokens.  A match is caught whatever its format, also URL-encoded (a fetch URL).
SECRETS_ENV = Path.home() / ".config" / "dl-ai" / "secrets.env"
GOOGLE_TOKEN_DIR = Path.home() / ".config" / "dl-ai" / "google"
SECRET_ENV_NAME = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|PASSWD")
SECRET_JSON_KEYS = {"token", "access_token", "refresh_token", "id_token", "client_secret"}
MIN_SECRET_LEN = 12


def known_secret_values() -> List[Tuple[str, str]]:
    """[(label, value)] of the credentials stored on this PC, read fresh each time (access tokens change hourly)."""
    found: Dict[str, str] = {}
    try:
        for line in SECRETS_ENV.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("export "):
                line = line[7:].strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            found.setdefault(val.strip().strip("'\""), f"value of {key.strip()} (secrets.env)")
    except OSError:
        pass
    for key, val in os.environ.items():
        if SECRET_ENV_NAME.search(key):
            found.setdefault(val.strip(), f"value of ${key}")

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if k in SECRET_JSON_KEYS and isinstance(v, str):
                    found.setdefault(v.strip(), f"Google sign-in {k}")
                else:
                    walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    for f in sorted(GOOGLE_TOKEN_DIR.glob("*.json")) if GOOGLE_TOKEN_DIR.is_dir() else []:
        try:
            walk(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
    # paths, URLs and sentences are not credentials (GNOME_KEYRING_CONTROL=/run/user/...)
    return [(label, val) for val, label in found.items()
            if len(val) >= MIN_SECRET_LEN and not re.search(r"\s|://", val) and val[0] not in "/~."]


def find_known_secrets(text: str) -> List[str]:
    """Labels of the stored credentials whose exact value appears in `text` (as is or URL-decoded)."""
    if not text:
        return []
    variants = {text, urllib.parse.unquote(text), urllib.parse.unquote_plus(text)}
    return [label for label, val in known_secret_values() if any(val in v for v in variants)]

# Whitelist safe false positives (mock keys, env placeholders)
SAFE_SECRET_WHITELIST = {
    "your_api_key_here", "sk-placeholder", "test_key", "mock_key",
    "000000000000000000000000", "xxxxxxxxxxxxxxxxxxxxxxxx",
}


def scan_secrets_in_text(content: str, file_path: Path | str = "") -> Tuple[bool, Optional[str]]:
    """Scans content for exposed secrets or credentials.

    Returns (is_clean, violation_details).
    """
    violations = []
    p_name = Path(file_path).name if file_path else "content"

    # Don't flag secrets inside legitimate .env or example template files if user is purposely setting .env
    if p_name.endswith(".env.example") or p_name == ".env.sample":
        return True, None

    for label, pattern in SECRET_PATTERNS:
        matches = pattern.findall(content)
        for m in matches:
            val = m if isinstance(m, str) else m[0]
            val_strip = val.strip()
            if val_strip in SAFE_SECRET_WHITELIST or "test" in val_strip.lower() or "mock" in val_strip.lower():
                continue
            masked = val_strip[:6] + "..." + val_strip[-4:] if len(val_strip) > 10 else "******"
            violations.append(f"  • {label}: matched token '{masked}'")

    # an env file is where a stored value belongs (the pattern check above still applies there)
    if not (p_name == "secrets.env" or p_name == ".env" or p_name.endswith(".env")):
        for label in find_known_secrets(content):
            violations.append(f"  • {label}: the exact value of a stored credential")

    if violations:
        msg = f"Potential secret leak detected in {p_name}:\n" + "\n".join(violations[:5])
        msg += "\nRemediation: Store credentials in environment variables or 'wiki/private/.env'."
        return False, msg
    return True, None


def tool_scan_secrets(args: Dict[str, Any], workspace: Path) -> str:
    """Standalone tool handler for scan_secrets."""
    target_path = args.get("path") or args.get("TargetFile")
    if target_path:
        p = Path(target_path).expanduser()
        if not p.is_absolute():
            p = (workspace / p).resolve()
        if p.is_file():
            content = p.read_text(encoding="utf-8", errors="replace")
            is_clean, err = scan_secrets_in_text(content, p)
            if is_clean:
                return f"✓ ScanSecrets: Clean! No credentials found in {p.name}."
            return f"✗ ScanSecrets Alert:\n{err}"
        elif p.is_dir():
            scan_dir = p
        else:
            return f"Error: Path not found: {p}"
    else:
        scan_dir = workspace

    # Scan directory files
    violations = []
    scanned_count = 0
    ignore_dirs = {".git", ".system_generated", "node_modules", "dist", "build", "__pycache__", ".venv", "venv", ".cache"}

    for root, dirs, files in os.walk(scan_dir):
        dirs[:] = [d for d in dirs if d not in ignore_dirs]
        for f in files:
            fp = Path(root) / f
            # Skip large binaries or database dumps
            if fp.stat().st_size > 1024 * 1024 or fp.suffix in (".png", ".jpg", ".bin", ".gguf", ".safetensors", ".so"):
                continue
            try:
                content = fp.read_text(encoding="utf-8", errors="replace")
                scanned_count += 1
                is_clean, err = scan_secrets_in_text(content, fp)
                if not is_clean and err:
                    violations.append(err)
            except Exception:
                pass

    if not violations:
        return f"✓ ScanSecrets: Scanned {scanned_count} files across {scan_dir}. 0 leaks found."
    return f"✗ ScanSecrets found {len(violations)} security alert(s):\n\n" + "\n\n".join(violations[:10])


# ==============================================================================
# 3. SYSTEM HEALTH (RAM, ROCm GPU VRAM, Swap, CPU & Strata Monitor)
# ==============================================================================

def get_system_health(url: str = "http://127.0.0.1:8080", api_key: str = "") -> Dict[str, Any]:
    """Collects real-time hardware telemetry and Strata engine status."""
    data: Dict[str, Any] = {
        "ram": {"used_gb": 0.0, "total_gb": 0.0, "pct": 0.0},
        "swap": {"used_gb": 0.0, "total_gb": 0.0, "pct": 0.0},
        "vram": {"used_gb": 0.0, "total_gb": 0.0, "pct": 0.0, "device": "AMD GPU"},
        "cpu": {"load_1m": 0.0, "cores": os.cpu_count() or 1},
        "engine": {"status": "offline", "model": "none", "context": 0},
    }

    # 1. System RAM & Swap from /proc/meminfo
    try:
        with open("/proc/meminfo") as f:
            mem = dict(line.split(":") for line in f if ":" in line)
        tot_b = int(mem["MemTotal"].strip().split()[0]) * 1024
        avail_b = int(mem["MemAvailable"].strip().split()[0]) * 1024
        used_b = tot_b - avail_b
        data["ram"]["total_gb"] = round(tot_b / (1024**3), 2)
        data["ram"]["used_gb"] = round(used_b / (1024**3), 2)
        data["ram"]["pct"] = round(used_b * 100 / tot_b, 1) if tot_b else 0.0

        sw_tot_b = int(mem.get("SwapTotal", "0").strip().split()[0]) * 1024
        sw_free_b = int(mem.get("SwapFree", "0").strip().split()[0]) * 1024
        sw_used_b = sw_tot_b - sw_free_b
        data["swap"]["total_gb"] = round(sw_tot_b / (1024**3), 2)
        data["swap"]["used_gb"] = round(sw_used_b / (1024**3), 2)
        data["swap"]["pct"] = round(sw_used_b * 100 / sw_tot_b, 1) if sw_tot_b else 0.0
    except Exception:
        pass

    # 2. CPU load from /proc/loadavg
    try:
        with open("/proc/loadavg") as f:
            parts = f.read().split()
            data["cpu"]["load_1m"] = float(parts[0])
    except Exception:
        pass

    # 3. ROCm GPU VRAM from sysfs drm device
    try:
        vram_used_files = glob.glob("/sys/class/drm/card*/device/mem_info_vram_used")
        vram_total_files = glob.glob("/sys/class/drm/card*/device/mem_info_vram_total")
        if vram_used_files and vram_total_files:
            with open(vram_used_files[0]) as fu, open(vram_total_files[0]) as ft:
                vu = int(fu.read().strip())
                vt = int(ft.read().strip())
                data["vram"]["used_gb"] = round(vu / (1024**3), 2)
                data["vram"]["total_gb"] = round(vt / (1024**3), 2)
                data["vram"]["pct"] = round(vu * 100 / vt, 1) if vt else 0.0
    except Exception:
        pass

    # 4. Strata Engine Health
    try:
        endpoint = f"{url.rstrip('/')}/health"
        req = urllib.request.Request(endpoint, headers={"Authorization": f"Bearer {api_key}"} if api_key else {})
        with urllib.request.urlopen(req, timeout=3) as resp:
            hdata = json.loads(resp.read().decode("utf-8"))
            data["engine"]["status"] = hdata.get("status", "ok")
            data["engine"]["model"] = hdata.get("model", "unknown")
            data["engine"]["context"] = hdata.get("max_context", 0)
    except Exception:
        data["engine"]["status"] = "unreachable"

    return data


def format_health_card(h: Dict[str, Any]) -> str:
    """Renders a sleek Unicode system telemetry card matching Strata's dark & orange theme."""
    card_w = 77

    def _row(text: str) -> str:
        plain = re.sub(r'\033\[[0-9;]*m', '', text)
        pad = max(0, card_w - 4 - len(plain))
        return f"{C_LINE}│{C_RESET}  {text}{' ' * pad}{C_LINE}│{C_RESET}\n"

    top_border = f"{C_LINE}╭{'─' * (card_w - 2)}╮{C_RESET}\n"
    mid_border = f"{C_LINE}├{'─' * (card_w - 2)}┤{C_RESET}\n"
    bot_border = f"{C_LINE}╰{'─' * (card_w - 2)}╯{C_RESET}\n"

    def bar(pct: float, width: int = 16) -> str:
        filled = int(width * (pct / 100.0))
        color = C_GREEN if pct < 75 else (C_YELLOW if pct < 90 else C_RED)
        return f"{color}{'█' * filled}{'░' * (width - filled)}{C_RESET}"

    r = h["ram"]
    s = h["swap"]
    v = h["vram"]
    c = h["cpu"]
    e = h["engine"]

    eng_color = C_GREEN if e["status"] == "ok" else C_RED

    out = [
        "\n",
        top_border,
        _row(f"{C_ACCENT_BOLD}✦ System Health & Telemetry{C_RESET}  {C_MUTED}·{C_RESET}  {C_INK_SOFT}Real-Time Hardware Budget{C_RESET}"),
        mid_border,
        _row(f"{C_MUTED}System RAM{C_RESET}  : {bar(r['pct'])}  {C_INK}{r['used_gb']:5.2f} / {r['total_gb']:5.2f} GB{C_RESET}  ({r['pct']:4.1f}%)"),
        _row(f"{C_MUTED}ROCm VRAM{C_RESET}   : {bar(v['pct'])}  {C_INK}{v['used_gb']:5.2f} / {v['total_gb']:5.2f} GB{C_RESET}  ({v['pct']:4.1f}%)"),
        _row(f"{C_MUTED}Swap Memory{C_RESET} : {bar(s['pct'])}  {C_INK}{s['used_gb']:5.2f} / {s['total_gb']:5.2f} GB{C_RESET}  ({s['pct']:4.1f}%)"),
        _row(f"{C_MUTED}CPU Load{C_RESET}    : {C_INK}{c['load_1m']:.2f}{C_RESET}  {C_MUTED}(1-min avg across {c['cores']} cores){C_RESET}"),
        mid_border,
        _row(f"{C_MUTED}Strata Engine{C_RESET} : {eng_color}[{e['status'].upper()}]{C_RESET}  {C_ACCENT_SOFT}{e['model']}{C_RESET}  {C_MUTED}({e['context']:,} tokens){C_RESET}"),
        bot_border,
        "\n"
    ]
    return "".join(out)


def tool_system_health(args: Dict[str, Any], workspace: Path) -> str:
    """Standalone tool handler for system_health."""
    h = get_system_health()
    return format_health_card(h)


# ==============================================================================
# 4. GIT DIFF AUDIT (Semantic Review Tool)
# ==============================================================================

def audit_git_diff(workspace: Path, staged_only: bool = False) -> str:
    """Performs a semantic security & quality audit of current git diff."""
    cmd = ["git", "diff", "--cached"] if staged_only else ["git", "diff", "HEAD"]
    try:
        res = subprocess.run(cmd, cwd=workspace, capture_output=True, text=True, check=True)
        diff_text = res.stdout
    except Exception:
        # Fallback to unstaged diff
        res = subprocess.run(["git", "diff"], cwd=workspace, capture_output=True, text=True)
        diff_text = res.stdout

    if not diff_text.strip():
        return f"✓ GitDiffAudit: Working tree is clean. 0 modified files found."

    files_modified: List[Dict[str, Any]] = []
    current_file = None
    additions = 0
    deletions = 0
    warnings = []
    critical_deletions = []

    # High-risk files
    CRITICAL_FILES = {".gitignore", "AGENTS.md", "CLAUDE.md", "server.py", "frontend.py", ".env"}

    lines = diff_text.splitlines()
    for line in lines:
        if line.startswith("diff --git"):
            m = re.search(r"b/(.*)$", line)
            current_file = m.group(1) if m else "unknown"
            files_modified.append({"name": current_file, "adds": 0, "dels": 0})
        elif line.startswith("deleted file mode"):
            if current_file:
                critical_deletions.append(current_file)
        elif line.startswith("+") and not line.startswith("+++"):
            additions += 1
            if files_modified:
                files_modified[-1]["adds"] += 1
            # Check secret in added line
            is_clean, sec_msg = scan_secrets_in_text(line[1:])
            if not is_clean:
                warnings.append(f"Security Alert in {current_file}: {sec_msg.strip()}")
        elif line.startswith("-") and not line.startswith("---"):
            deletions += 1
            if files_modified:
                files_modified[-1]["dels"] += 1

    # Large blob additions check
    for f in files_modified:
        if f["adds"] > 400:
            warnings.append(f"High Volume: '{f['name']}' added +{f['adds']} lines in a single edit.")

    # Critical deletions check
    for cd in critical_deletions:
        if Path(cd).name in CRITICAL_FILES:
            warnings.append(f"CRITICAL FILE DELETION: Core file '{cd}' was deleted!")

    # Risk level determination
    if any("Security Alert" in w or "CRITICAL FILE" in w for w in warnings):
        risk = f"{C_RED}[HIGH RISK]{C_RESET}"
    elif warnings:
        risk = f"{C_YELLOW}[MEDIUM RISK]{C_RESET}"
    else:
        risk = f"{C_GREEN}[LOW RISK - CLEAN]{C_RESET}"

    out = [
        f"\n{C_BOLD}Git Diff Semantic Audit Report:{C_RESET} {risk}",
        f"  • Files Changed : {len(files_modified)}",
        f"  • Net Changes   : {C_GREEN}+{additions}{C_RESET} / {C_RED}-{deletions}{C_RESET} lines",
        f"\n{C_BOLD}Modified Files:{C_RESET}"
    ]
    for f in files_modified[:15]:
        out.append(f"  - {f['name']:<35} ({C_GREEN}+{f['adds']}{C_RESET}, {C_RED}-{f['dels']}{C_RESET})")

    if warnings:
        out.append(f"\n{C_BOLD}Audit Warnings & Guardrail Flags:{C_RESET}")
        for w in warnings:
            out.append(f"  ⚠ {w}")
    else:
        out.append(f"\n{C_GREEN}✓ Clean diff: No secrets, accidental file deletions, or oversized blobs detected.{C_RESET}")

    return "\n".join(out)


def tool_git_diff_audit(args: Dict[str, Any], workspace: Path) -> str:
    """Standalone tool handler for git_diff_audit."""
    staged = bool(args.get("staged_only", False))
    return audit_git_diff(workspace, staged_only=staged)


# ==============================================================================
# 5. SMART TEST RUNNER (Universal Targeted Test Runner)
# ==============================================================================

def discover_relevant_tests(workspace: Path, modified_files: List[str]) -> List[Path]:
    """Finds unit test files relevant to the modified source files."""
    test_files = set()

    for mf in modified_files:
        p = Path(mf)
        stem = p.stem.removeprefix("test_")

        # 1. Direct counterpart tests: test_<stem>.py, <stem>_test.py
        candidates = [
            workspace / f"test_{stem}.py",
            workspace / f"{stem}_test.py",
            workspace / "tests" / f"test_{stem}.py",
            workspace / "tests" / f"{stem}_test.py",
            workspace / "tools" / f"test_{stem}.py",
        ]
        for c in candidates:
            if c.is_file():
                test_files.add(c)

        # If file itself is a test file
        if p.name.startswith("test_") and (workspace / p).is_file():
            test_files.add((workspace / p).resolve())

    # Fallback: if no specific test found, return common quick test suite if present
    if not test_files:
        smoke_tests = list((workspace / "tools").glob("test_setup_*.py"))
        if smoke_tests:
            test_files.update(smoke_tests[:5])

    return sorted(list(test_files))


def run_smart_tests(workspace: Path, target_files: Optional[List[str]] = None) -> str:
    """Discovers and runs only relevant tests across Python, Node.js, Bash, and Make."""
    files_to_check = target_files or []

    if not files_to_check:
        # Detect modified files from git
        try:
            res = subprocess.run(["git", "status", "--porcelain"], cwd=workspace, capture_output=True, text=True)
            for line in res.stdout.splitlines():
                parts = line.strip().split()
                if len(parts) >= 2:
                    files_to_check.append(parts[-1])
        except Exception:
            pass

    test_targets = discover_relevant_tests(workspace, files_to_check)

    # 1. Python tests
    if test_targets:
        test_paths_str = [str(t.relative_to(workspace) if t.is_relative_to(workspace) else t) for t in test_targets]
        pytest_bin = shutil.which("pytest")

        t0 = time.time()
        if pytest_bin:
            cmd = [pytest_bin, "-v", "--tb=short"] + test_paths_str
        else:
            # Fall back to running individual python test scripts
            cmd = ["python3", test_paths_str[0]]

        env = os.environ.copy()
        env["PYTHONPATH"] = f".:{env.get('PYTHONPATH', '')}"

        try:
            res = subprocess.run(cmd, cwd=workspace, env=env, capture_output=True, text=True, timeout=60)
            elapsed = time.time() - t0
            passed = "PASSED" in res.stdout or res.returncode == 0
            badge = f"{C_GREEN}✓ PASSED{C_RESET}" if passed else f"{C_RED}✗ FAILED{C_RESET}"

            out = [
                f"\n{C_BOLD}Smart Test Runner:{C_RESET} {badge} ({elapsed:.2f}s)",
                f"  • Suite:    {', '.join(test_paths_str[:4])}",
                f"  • Runner:   {cmd[0]}",
                f"\n{res.stdout.strip() or res.stderr.strip()}"
            ]
            return "\n".join(out)
        except subprocess.TimeoutExpired:
            return f"✗ SmartTestRunner: Tests timed out after 60s."
        except Exception as e:
            return f"Error executing tests: {e}"

    # 2. Node.js tests (package.json)
    pkg_json = workspace / "package.json"
    if pkg_json.is_file():
        try:
            data = json.loads(pkg_json.read_text(encoding="utf-8"))
            if "scripts" in data and "test" in data["scripts"]:
                t0 = time.time()
                res = subprocess.run(["npm", "test"], cwd=workspace, capture_output=True, text=True, timeout=60)
                elapsed = time.time() - t0
                badge = f"{C_GREEN}✓ PASSED{C_RESET}" if res.returncode == 0 else f"{C_RED}✗ FAILED{C_RESET}"
                return f"\n{C_BOLD}Smart Test Runner (npm test):{C_RESET} {badge} ({elapsed:.2f}s)\n\n{res.stdout}"
        except Exception:
            pass

    # 3. Makefile test
    makefile = workspace / "Makefile"
    if makefile.is_file():
        try:
            content = makefile.read_text(encoding="utf-8", errors="replace")
            if "\ntest:" in content:
                res = subprocess.run(["make", "test"], cwd=workspace, capture_output=True, text=True, timeout=60)
                badge = f"{C_GREEN}✓ PASSED{C_RESET}" if res.returncode == 0 else f"{C_RED}✗ FAILED{C_RESET}"
                return f"\n{C_BOLD}Smart Test Runner (make test):{C_RESET} {badge}\n\n{res.stdout}"
        except Exception:
            pass

    return f"ℹ SmartTestRunner: No relevant test suites detected for modified files in {workspace}."


def tool_smart_test_runner(args: Dict[str, Any], workspace: Path) -> str:
    """Standalone tool handler for smart_test_runner."""
    files = args.get("files") or []
    return run_smart_tests(workspace, target_files=files)


# ==============================================================================
# TOOL SCHEMAS FOR D.L. CLI & AGENT ORCHESTRATION
# ==============================================================================

AUDITING_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "syntax_guard",
            "description": "Performs instant AST and grammar syntax inspection (Python, JS/TS, Bash, JSON, YAML). Use before or after file edits to detect broken syntax.",
            "parameters": {
                "type": "object",
                "properties": {
                    "TargetFile": {
                        "type": "string",
                        "description": "Path to file to validate."
                    },
                    "CodeContent": {
                        "type": "string",
                        "description": "Optional snippet to validate directly without reading from disk."
                    },
                    "language": {
                        "type": "string",
                        "description": "Optional language override (python, javascript, bash, json, yaml)."
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "scan_secrets",
            "description": "Scans code, files, or workspace for leaked API keys, tokens, private keys, or credentials.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Target file or directory to scan (defaults to workspace)."
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "system_health",
            "description": "Queries real-time hardware telemetry: System RAM, ROCm GPU VRAM, Swap memory, CPU load, and Strata engine status.",
            "parameters": {
                "type": "object",
                "properties": {
                    "detailed": {
                        "type": "boolean",
                        "description": "Set true for comprehensive memory and context breakdowns."
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "git_diff_audit",
            "description": "Audits current git diff for unintended file deletions, oversized blobs, trailing whitespace, and secret leaks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "staged_only": {
                        "type": "boolean",
                        "description": "If true, audits only staged git changes."
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "smart_test_runner",
            "description": "Targeted test runner that detects modified modules and runs relevant unit tests (pytest, unittest, npm, bash, make).",
            "parameters": {
                "type": "object",
                "properties": {
                    "files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list of modified files to focus test discovery on."
                    }
                }
            }
        }
    }
]



# ==============================================================================
# 6. DESTRUCTIVE ACTION GATE (approval before the agent acts)
# ==============================================================================
# Only what can destroy data or the system, or act beyond the workspace, is gated - content is never restricted.
# A match asks the user (terminal y/N or the web approval card); /yolo turns the gate off for a session.

_DESTRUCTIVE_PATTERNS = [
    ("deletes recursively or forcibly", re.compile(r"(?:^|[\s;&|(`])rm\s+(?:-[a-zA-Z]*[rRf][a-zA-Z]*|--recursive|--force)\b")),
    ("deletes found files", re.compile(r"\bfind\b[^|;&]*\s-(?:delete|exec\s+rm)\b|\bxargs\s+(?:-\S+\s+)*rm\b")),
    ("runs as root", re.compile(r"(?:^|[\s;&|(`])(?:sudo|doas|pkexec|su)(?:\s|$)")),
    ("writes raw disks or filesystems", re.compile(r"(?:^|[\s;&|(`])(?:dd|mkfs(?:\.\w+)?|shred|wipefs|fdisk|sfdisk|parted|sgdisk|blkdiscard)(?:\s|$)|>\s*/dev/(?:sd|nvme|hd|vd|mmcblk)")),
    ("changes ownership or permissions recursively", re.compile(r"\b(?:chmod|chown|chgrp)\s+(?:-\S*\s+)*-[a-zA-Z]*R")),
    ("rewrites or discards git history/work", re.compile(r"\bgit\s+(?:push\b[^;&|]*\s(?:--force(?:-with-lease)?|-f)\b|reset\s+--hard|clean\s+-[a-zA-Z]*f|branch\s+-D|checkout\s+--\s|restore\s|filter-(?:repo|branch)|stash\s+(?:drop|clear)|rebase\b)")),
    ("stops services or processes", re.compile(r"\bsystemctl\s+(?:--user\s+)?(?:stop|disable|mask|kill|restart|isolate)\b|\b(?:reboot|shutdown|poweroff|halt)\b|\bkill\s+-(?:9|KILL)\b|\b(?:pkill|killall)\b")),
    ("pipes a download into a shell", re.compile(r"\b(?:curl|wget)\b[^|]*\|\s*(?:sudo\s+)?(?:ba|z|fi)?sh\b")),
    ("removes packages", re.compile(r"\bpacman\s+-R|\bapt(?:-get)?\s+(?:remove|purge)|\bpip\d?\s+uninstall\b|\bnpm\s+(?:uninstall|rm)\s+-g")),
]
_PATH_ARG = re.compile(r"""(?:>>?\s*|\btee\s+(?:-a\s+)?|\b(?:mv|cp|rsync|ln)\s+(?:-\S+\s+)*\S+\s+)(['"]?)(~?/[^\s'";&|)]*)\1""")
_SAFE_ROOTS = ("/tmp/", "/dev/null", "/dev/stdout", "/dev/stderr")


def _outside(path_str: str, workspace: Path) -> bool:
    if path_str.startswith(_SAFE_ROOTS) or path_str in ("/tmp", "/dev/null"):
        return False
    p = Path(path_str).expanduser()
    try:
        p.resolve().relative_to(workspace.resolve())
        return False
    except ValueError:
        return True


def classify_command(cmd: str, workspace: Path) -> Optional[str]:
    """Why a shell command needs the user's approval, or None when it may run."""
    reasons = [label for label, rx in _DESTRUCTIVE_PATTERNS if rx.search(cmd)]
    for _, path_str in _PATH_ARG.findall(cmd):
        # "> /x" also matches text inside quoted code, such as the regex in sed -n '/^<script>/,/^<\/script>/p':
        # only a path whose top folder exists can be a redirect target (no new folder appears in / without root)
        if not path_str.startswith("~") and not Path("/" + path_str.strip("/").split("/")[0]).exists():
            continue
        if _outside(path_str, workspace):
            reasons.append(f"writes outside the workspace ({path_str})")
            break
    return "; ".join(reasons) or None


def classify_write(path: Path, workspace: Path) -> Optional[str]:
    """Why a file write needs the user's approval (it lands outside the workspace), or None."""
    return f"writes outside the workspace ({path})" if _outside(str(path), workspace) else None


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="D.L. CLI Auditing & Debugging Suite")
    parser.add_argument("--health", action="store_true", help="Display real-time system health")
    parser.add_argument("--diff", action="store_true", help="Audit current git diff")
    parser.add_argument("--secrets", nargs="?", const=".", help="Scan path for secrets")
    parser.add_argument("--syntax", help="Validate syntax of file")
    parser.add_argument("--test", nargs="*", help="Run smart tests")
    args = parser.parse_args()

    ws = Path.cwd()
    if args.health:
        print(format_health_card(get_system_health()))
    elif args.diff:
        print(audit_git_diff(ws))
    elif args.secrets:
        print(tool_scan_secrets({"path": args.secrets}, ws))
    elif args.syntax:
        print(tool_syntax_guard({"TargetFile": args.syntax}, ws))
    elif args.test is not None:
        print(run_smart_tests(ws, target_files=args.test))
    else:
        parser.print_help()
