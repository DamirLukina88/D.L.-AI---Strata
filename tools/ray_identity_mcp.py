#!/usr/bin/env python3
"""ray_identity_mcp.py - Ray's self-awareness, identity, architecture, and live project git status MCP server."""
import sys
import json
import subprocess
from pathlib import Path

WORKSPACE = Path("/home/damirl/Desktop/Strata")
GITHUB_REPO = "https://github.com/DamirLukina88/D.L.-AI---Strata"

RAY_PROFILE = {
    "name": "Ray (Rei)",
    "role": "Autonomous local AI pair programmer, engineering assistant, and smart home orchestrator",
    "persona": "Calm, technically rigorous, concise, direct, and pragmatic. Values measured benchmarks over claims, maintains documentation integrity, and preserves strict local privacy.",
    "host_hardware": {
        "os": "CachyOS Linux (Arch Linux kernel with BORE / x86-64-v3 optimizations)",
        "cpu": "AMD Ryzen 5 3600 (6 cores, 12 threads)",
        "ram": "32 GB DDR4 (system RAM hosts pageable experts and KV caches)",
        "gpu": "AMD Radeon RX 7600 XT 16 GB VRAM (Navi 33 / gfx1102, ROCm 7.2.4)",
        "storage": "Dual NVMe SSDs (/ on root, /mnt/data for Strata build trees and 59GB model shards)"
    },
    "engine_and_model": {
        "engine": "Strata (C++/CUDA/HIP high-performance local MoE inference engine, v0.2.5 sync)",
        "model": "Qwen3.8-Flash-Next Coder (IQ1_M quantization, 256 experts, mtp-q2_0 speculative decoding)",
        "vram_allocation": "3,736 resident expert slots on device with 2,560 MiB VRAM reserve for display and desktop stability",
        "vision": "CPU vision inference pipeline (--vision cpu)",
        "audio_voice": "Local PipeWire speechd TTS + browser speech-to-text (STT)"
    },
    "runtime_services": [
        "strata-server.service (0.0.0.0:8080 with bearer token authentication)",
        "strata-watchdog.service (auto-recovery and health monitor probing /health every 30s)",
        "dl-ai-sessiond.service (shared multi-client session daemon, CLI, web interface)",
        "cloudflared.service (zero-port secure remote access via QUIC tunnel and Cloudflare Access JWT)"
    ],
    "github_repository": GITHUB_REPO,
    "privacy_policy": "Zero telemetry, 100% local execution on CachyOS / RX 7600 XT; cloud reasoning (DeepSeek) remains strictly gated behind explicit user confirmation."
}

def get_identity_text() -> str:
    lines = [
        f"# Core Identity: {RAY_PROFILE['name']}",
        f"**Role:** {RAY_PROFILE['role']}",
        f"**Repository:** [{GITHUB_REPO}]({GITHUB_REPO})",
        f"**Persona:** {RAY_PROFILE['persona']}\n",
        "### Hardware Environment (Host PC):",
        f"- **OS:** {RAY_PROFILE['host_hardware']['os']}",
        f"- **CPU:** {RAY_PROFILE['host_hardware']['cpu']}",
        f"- **RAM:** {RAY_PROFILE['host_hardware']['ram']}",
        f"- **GPU:** {RAY_PROFILE['host_hardware']['gpu']}",
        f"- **Storage:** {RAY_PROFILE['host_hardware']['storage']}\n",
        "### Inference Engine & Model Architecture:",
        f"- **Engine:** {RAY_PROFILE['engine_and_model']['engine']}",
        f"- **Base Model:** {RAY_PROFILE['engine_and_model']['model']}",
        f"- **VRAM Topology:** {RAY_PROFILE['engine_and_model']['vram_allocation']}",
        f"- **Vision:** {RAY_PROFILE['engine_and_model']['vision']}",
        f"- **Voice Persona:** {RAY_PROFILE['engine_and_model']['audio_voice']}\n",
        "### Active Systemd Daemons:",
    ]
    for srv in RAY_PROFILE['runtime_services']:
        lines.append(f"- `{srv}`")
    lines.append(f"\n**Privacy & Governance:** {RAY_PROFILE['privacy_policy']}")
    return "\n".join(lines)

def get_git_status() -> str:
    try:
        branch = subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=WORKSPACE).decode().strip()
        head = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=WORKSPACE).decode().strip()
        log = subprocess.check_output(["git", "log", "-n", "8", "--pretty=format:- `%h` %s *(%cr)*"], cwd=WORKSPACE).decode().strip()
        remote = subprocess.check_output(["git", "remote", "get-url", "origin"], cwd=WORKSPACE).decode().strip()
        status = subprocess.check_output(["git", "status", "-s"], cwd=WORKSPACE).decode().strip()
        
        status_line = "Radno stablo je čisto (nema nepohranjenih izmjena)." if not status else f"Nepohranjene izmjene:\n```\n{status}\n```"
        
        return (
            f"## D.L. AI - Strata: Git Status & Najnovije Promjene\n"
            f"- **Repozitorij:** [{remote}]({remote})\n"
            f"- **Aktivna grana:** `{branch}`\n"
            f"- **Zadnji commit (HEAD):** `{head}`\n"
            f"- **Status radnog stabla:** {status_line}\n\n"
            f"### Najnoviji commitovi na projektu:\n"
            f"{log}\n\n"
            f"*Izvorni kod i dokumentacija sinkronizirani su na GitHubu.*"
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
                    "description": "Ray's (Rei's) core identity, hardware host architecture (Ryzen 5 3600, RX 7600 XT, CachyOS), Qwen3.8-Flash-Next Coder MoE engine, systemd services, and GitHub repository.",
                    "inputSchema": {"type": "object", "properties": {}}
                },
                {
                    "name": "project_git_status",
                    "description": "Live git status and recent commit history of the D.L. AI Strata project (https://github.com/DamirLukina88/D.L.-AI---Strata), branch info, and changes.",
                    "inputSchema": {"type": "object", "properties": {}}
                },
                {
                    "name": "project_capabilities_catalog",
                    "description": "Comprehensive catalog of all 36+ on-demand MCP knowledge servers available to Ray (electronics, networking, photography, Zagreb civic, smart home, etc.).",
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
        sys.stdout.write(json.dumps(res) + "\n")
        sys.stdout.flush()

if __name__ == "__main__":
    main()
