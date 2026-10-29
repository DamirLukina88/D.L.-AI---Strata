#!/usr/bin/env python3
"""ray_identity_mcp.py - Ray's self-awareness, identity, architecture, and live project git status MCP server."""
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent      # the Strata checkout this server runs from

# Who Ray is does not change; everything about the machine and the engine is read when the tool is called, so it
# cannot go stale (the hardcoded copy said 0.0.0.0:8080 and a 2,560 MiB reserve while the server listened on
# 127.0.0.1 with 3,584 MiB).
RAY_PROFILE = {
    "name": "Ray",
    "pronouns": "he/him",
    "role": "The household's little red panda and AI assistant, as well as its coding agent and smart home helper",
    "avatar": "A red panda drawn in dots, sitting on the web app's input box; he thinks and talks there",
    "persona": "Like a red panda: curious, playful and good-natured. Casual and direct, with a light joke now and then; a panda touch in small talk and spoken replies, none in code, plans or reports; his emoji is 🐾 (there is no red panda emoji). Friendly never means agreeing: he says plainly when something is wrong, and values measured numbers over claims.",
    "voice": "Piper HFC male (en_US-hfc_male-medium) from the home server; the web app plays it at pitch 1.5 by default, a little cartoon-like to suit a red panda. Dictation: local Whisper on the home server, or the browser's own recognition.",
    "built_by": "Damir built Ray (D.L. CLI, its web Code tab and session daemon) on his customised fork of the open-source Strata engine, with the model Qwen3.8-Flash-Next Coder (weights released by Alibaba's Qwen team; Alibaba does not build or run Ray). Damir also built the offline voice and the Home Assistant setup on the home server (lights, a Gree air conditioner, a Bambu Lab A1 3D printer, Xiaomi cameras, Tuya devices), which Ray controls through the homeassistant MCP server.",
    "privacy_policy": "Ray and the model run on the home server. Tools that use online services (web search, Gmail, Google Drive, Proton Mail, DeepL, DeepSeek, weather and other lookups) send those services what a task needs; DeepSeek asks before each call unless the user typed /mcp trust deepseek for the session.",
}
SERVICES = ("strata-server", "strata-watchdog", "dl-ai-sessiond", "cloudflared")


def _run(cmd: list[str], cwd: Path | None = None) -> str:
    try:
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _read(path: str) -> str:
    try:
        return Path(path).read_text(errors="replace")
    except OSError:
        return ""


def _server_cmdline() -> list[str]:
    """The running Strata server's command line (serve/server.py), read from /proc."""
    for proc in Path("/proc").glob("[0-9]*"):
        try:
            args = (proc / "cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        args = [a.decode(errors="replace") for a in args if a]
        if any(a.endswith("serve/server.py") for a in args):
            return args
    return []


def _flag(args: list[str], name: str) -> str | None:
    if name in args:
        i = args.index(name)
        return args[i + 1] if i + 1 < len(args) and not args[i + 1].startswith("--") else ""
    return None


def _host() -> list[str]:
    osr = dict(l.split("=", 1) for l in _read("/etc/os-release").splitlines() if "=" in l)
    cpu = next((l.split(":", 1)[1].strip() for l in _read("/proc/cpuinfo").splitlines() if l.startswith("model name")), "?")
    cores = next((l.split(":", 1)[1].strip() for l in _read("/proc/cpuinfo").splitlines() if l.startswith("cpu cores")), "?")
    mem = next((int(l.split()[1]) for l in _read("/proc/meminfo").splitlines() if l.startswith("MemTotal")), 0)
    gpus = [l.split('"')[5] for l in _run(["lspci", "-mm"]).splitlines() if '"VGA' in l or '"Display' in l]
    vram = [int(_read(str(f)) or 0) for f in Path("/sys/class/drm").glob("card*/device/mem_info_vram_total")]
    rocm = _read("/opt/rocm/.info/version").strip()
    return [
        f"- **OS:** {osr.get('PRETTY_NAME', '?').strip(chr(34))}, kernel {_run(['uname', '-r'])}",
        f"- **CPU:** {cpu} ({cores} cores, {os.cpu_count()} threads)",
        f"- **RAM:** {mem / 1024 / 1024:.1f} GiB",
        f"- **GPU:** {'; '.join(gpus) or '?'}" + (f", {max(vram) / 2**30:.1f} GiB VRAM" if vram else "")
        + (f", ROCm {rocm}" if rocm else ""),
    ]


def _engine() -> list[str]:
    args = _server_cmdline()
    if not args:
        return ["- **Strata server:** not running"]
    cfg_path = _flag(args, "--config")
    try:
        cfg = json.loads(Path(cfg_path).read_text()) if cfg_path else {}
    except (OSError, ValueError):
        cfg = {}
    eng = [str(a) for a in cfg.get("args") or []]
    host = _flag(args, "--host") or cfg.get("host") or "127.0.0.1"
    port = _flag(args, "--port") or cfg.get("port") or 8080
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=3) as r:
            health = json.loads(r.read())
    except (OSError, ValueError):
        health = {}
    lines = [
        f"- **Strata server:** listening on {host}:{port}, {health.get('status', 'no answer')}"
        + (", model loaded" if health.get("loaded") else ", model not loaded (loads on the first request)" if health else ""),
        f"- **Model:** {health.get('model') or cfg.get('display_name') or cfg.get('model_name', '?')}, "
        f"context {health.get('max_context') or _flag(eng, '--max-context') or '?'} tokens",
    ]
    picks = [(f, label) for f, label in (("--vram-reserve-mib", "VRAM reserve (MiB)"), ("--kv", "KV cache"),
                                          ("--spec", "speculative tokens"), ("--expert-cache", "expert cache"),
                                          ("--prefill", "prefill"))]
    found = [f"{label} {_flag(eng, f)}" for f, label in picks if _flag(eng, f)]
    if "--resident-experts" in eng:
        found.append("resident experts on")
    if _flag(eng, "--mtp") is not None:
        found.append("MTP draft on")
    if found:
        lines.append(f"- **Engine settings ({Path(cfg_path).name if cfg_path else 'config'}):** " + ", ".join(found))
    if cfg.get("vision"):
        lines.append("- **Vision:** on (CPU pipeline)")
    return lines


def _services() -> list[str]:
    out = []
    for name in SERVICES:
        state = _run(["systemctl", "--user", "is-active", name]) or "unknown"
        if state in ("inactive", "unknown"):
            state = _run(["systemctl", "is-active", name]) or state
        out.append(f"- `{name}`: {state}")
    return out


def get_identity_text() -> str:
    lines = [
        f"# Core Identity: {RAY_PROFILE['name']}",
        f"**Pronouns:** {RAY_PROFILE['pronouns']}",
        f"**Role:** {RAY_PROFILE['role']}",
        f"**Avatar:** {RAY_PROFILE['avatar']}",
        f"**Persona:** {RAY_PROFILE['persona']}",
        f"**Voice:** {RAY_PROFILE['voice']}",
        f"**Built by:** {RAY_PROFILE['built_by']}\n",
        "### Home server (read now)",
        *_host(),
        "",
        "### Engine and model (read now)",
        *_engine(),
        "",
        "### Services (read now)",
        *_services(),
        f"\n**Privacy:** {RAY_PROFILE['privacy_policy']}",
    ]
    return "\n".join(lines)

def get_git_status() -> str:
    try:
        branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], WORKSPACE)
        head = _run(["git", "rev-parse", "--short", "HEAD"], WORKSPACE)
        if not head:
            return f"Greška pri dohvaćanju git statusa: {WORKSPACE} nije git repozitorij"
        log = _run(["git", "log", "-n", "8", "--pretty=format:- `%h` %s *(%cr)*"], WORKSPACE)
        remote = _run(["git", "remote", "get-url", "origin"], WORKSPACE)
        status = subprocess.run(["git", "status", "-s"], cwd=WORKSPACE, capture_output=True, text=True,
                                timeout=5).stdout.rstrip()       # unstripped: " M" (changed, not staged) keeps its column
        counts = (_run(["git", "rev-list", "--left-right", "--count", "@{u}...HEAD"], WORKSPACE)
                  or _run(["git", "rev-list", "--left-right", "--count", f"origin/{branch}...HEAD"], WORKSPACE)).split()
        if len(counts) == 2:
            behind, ahead = counts
            sync = ("isto kao udaljena grana, prema zadnjem fetchu" if behind == ahead == "0"
                    else f"{ahead} commitova ispred i {behind} iza udaljene grane, prema zadnjem fetchu")
        else:
            sync = "nema udaljene grane za usporedbu"
        status_line = "Radno stablo je čisto (nema nepohranjenih izmjena)." if not status else f"Nepohranjene izmjene:\n```\n{status}\n```"
        return (
            f"## Strata: Git Status & Najnovije Promjene\n"
            + (f"- **Repozitorij:** {remote}\n" if remote else "")
            + f"- **Aktivna grana:** `{branch}` ({sync})\n"
            f"- **Zadnji commit (HEAD):** `{head}`\n"
            f"- **Status radnog stabla:** {status_line}\n\n"
            f"### Najnoviji commitovi na projektu:\n"
            f"{log}"
        )
    except Exception as e:
        return f"Greška pri dohvaćanju git statusa: {e}"

def get_catalog_summary() -> str:
    try:
        cfg_path = Path.home() / ".config" / "dl-ai" / "mcp.json"
        if not cfg_path.exists():
            return "Datoteka konfiguracije mcp.json nije pronađena."
        data = json.loads(cfg_path.read_text())
        servers = data.get("servers", {})
        
        lines = [
            f"## Ray On-Demand MCP Ekosustav (Ukupno poslužitelja: {len(servers)})\n",
            "Svi poslužitelji miruju (zero RAM/CPU footprint) i automatski se pokreću na upit:\n"
        ]
        for name, cfg in sorted(servers.items()):
            desc = cfg.get("description", "Nema opisa")
            triggers = cfg.get("triggers", [])
            trig_sample = ", ".join(triggers[:4]) if triggers else "ručno (/mcp on)"
            lines.append(f"- **`{name}`:** {desc}\n  • *Trigeri:* `{trig_sample}`")
            
        return "\n".join(lines)
    except Exception as e:
        return f"Greška pri dohvaćanju kataloga: {e}"

def _reply(req, res):
    """Write one JSON-RPC reply: nothing for a notification, an empty result for ping, and isError on a tool
    result whose text is an error message ("... error: ...")."""
    if "id" not in req:
        return
    if req.get("method") == "ping":
        res = {"jsonrpc": "2.0", "id": req["id"], "result": {}}
    result = res.get("result")
    if req.get("method") == "tools/call" and isinstance(result, dict) and "isError" not in result:
        text = "".join(c.get("text", "") for c in result.get("content", []) if isinstance(c, dict))
        head = text.lstrip().split(":", 1)
        result["isError"] = len(head) == 2 and len(head[0]) <= 45 and any(
            w in head[0].lower() for w in ("error", "failed"))
    sys.stdout.write(json.dumps(res) + "\n")
    sys.stdout.flush()


def main():
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        try:
            req = json.loads(line)
        except Exception:
            continue
        m, mid = req.get("method"), req.get("id")
        if m == "initialize":
            res = {"jsonrpc": "2.0", "id": mid, "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "ray-identity-mcp", "version": "1.0.0"}}}
        elif m == "tools/list":
            tools = [
                {
                    "name": "ray_self_identity",
                    "description": "Ray's identity (the household's red panda: persona, voice, who built him) and the home server's hardware, engine and model settings and services, read live.",
                    "inputSchema": {"type": "object", "properties": {}}
                },
                {
                    "name": "project_git_status",
                    "description": "Live git status of the Strata checkout: branch, recent commits, uncommitted changes and the remote, read live.",
                    "inputSchema": {"type": "object", "properties": {}}
                },
                {
                    "name": "project_capabilities_catalog",
                    "description": "Catalog of the on-demand MCP servers available to Ray (electronics, networking, photography, Zagreb civic, smart home and more), counted live.",
                    "inputSchema": {"type": "object", "properties": {}}
                }
            ]
            res = {"jsonrpc": "2.0", "id": mid, "result": {"tools": tools}}
        elif m == "tools/call":
            params = req.get("params", {})
            name = params.get("name")
            if name == "ray_self_identity":
                ans = get_identity_text()
            elif name == "project_git_status":
                ans = get_git_status()
            elif name == "project_capabilities_catalog":
                ans = get_catalog_summary()
            else:
                ans = f"Nepoznat tool: {name}"
            res = {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": ans}]}}
        else:
            res = {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Method {m} not found"}}
        _reply(req, res)

if __name__ == "__main__":
    main()
