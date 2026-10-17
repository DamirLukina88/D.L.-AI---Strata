---
title: "Strata"
type: entity
description: "High-performance local AI workstation combining 125B MoE inference engine, D.L. CLI, DeepSeek live thinking, and web code terminal"
status: active
tags: [strata, inference-engine, moe, local-ai, workstation, dl-cli, claude-code]
created: 2026-10-05
updated: 2026-10-13
last_verified: 2026-10-11
---

# Strata (D.L. AI Workstation)

## Summary

Originally created as an open-source C++/HIP/CUDA inference engine to run 125-billion-parameter Mixture-of-Experts (MoE) models (Qwen3.8-Flash-Next and variants) on consumer PCs, Strata has evolved into a comprehensive, sovereign local AI developer workstation. 

The environment integrates high-throughput MoE execution (16 GB VRAM + 32 GB RAM) with autonomous CLI coding agents (D.L. CLI, Claude Code CLI, DeepSeek CLI), an authenticated Web Code terminal (`ttyd` integration), automated auditing and diagnostic guardrails, real-time reasoning visualization, and dedicated NVMe project storage (`/mnt/data/DL-AI-workspace`).

- 2026-10-13: Upstream v0.1.43.1 merged. The Code tab is now a client of the shared CLI session daemon (dl-ai-sessiond) instead of ttyd/tmux; the terminal joins the same session with dl_cli.py --attach. Browsers authenticate with the Cloudflare Access login. See [Shared CLI Session Daemon](../decisions/shared-cli-session-daemon.md).

## Key Facts

- **Inference Engine:** High-performance C++ core with CUDA, HIP (AMD RDNA3/4, gfx1102 RX 7600 XT), and SYCL backends. Features AVX2/AVX-512 CPU execution kernels, dynamic VRAM expert caching (90%+ hit rate), speculative draft acceleration, and CPU prefill expert sharing.
- **D.L. CLI (Autonomous Agent Harness):** Native Python agent harness featuring Claude Code-inspired dual execution modes (`PLAN` mode with read-only sandboxing and `ACT` mode for direct execution), proactive local wiki knowledge recall, and full auditing guardrails (`syntax_guard`, `scan_secrets`, `system_health`, `git_diff_audit`, `smart_test_runner`).
- **Claude Code CLI Integration:** Fully local execution pipeline with automatic lifecycle management (starts Strata on demand, stops on session exit), custom fit-max-tokens handling, isolated persistent memory, and stripped lean tool profiles.
- **DeepSeek CLI & Live Reasoning:** Local streaming interface featuring dual `Live` terminal panels for real-time visualization of model thinking/reasoning traces side-by-side with generated output.
- **Web Terminal & Code Workspace:** Embedded web terminal running authenticated tmux sessions in the browser alongside the Strata web UI, paired with a dedicated NVMe workspace (`/mnt/data/DL-AI-workspace`) accessible via web upload/download APIs.
- **API & Telemetry:** Full protocol compatibility with Anthropic (`v1/messages`), OpenAI (`v1/chat/completions`), OpenAI Responses API (`v1/responses`), and Prometheus metrics (`/metrics`).
- **Security & Privacy:** Offline-first architecture. All inference runs strictly on localhost (`127.0.0.1:8080`); remote access is secured via Cloudflare Tunnel with strict API key authentication and DNS rebinding protections.

## Architecture & Workstation Components

```
                                  +---------------------------------------------+
                                  |            Developer Entrypoints            |
                                  |  Web Terminal (ttyd) | Web GUI | Remote API |
                                  +----------------------+----------------------+
                                                         |
         +-----------------------------------------------+-----------------------------------------------+
         |                                               |                                               |
+--------------------+                         +--------------------+                         +--------------------+
|     D.L. CLI       |                         |  Claude Code CLI   |                         |    DeepSeek CLI    |
| • Plan / Act modes |                         | • On-demand daemon |                         | • Live thinking    |
| • Guardrails suite |                         | • Fable 5.1 prompt |                         |   stream display   |
| • Wiki auto-recall |                         | • Pure local tools |                         | • Rich formatting  |
+--------------------+                         +--------------------+                         +--------------------+
         |                                               |                                               |
         +-----------------------------------------------+-----------------------------------------------+
                                                         |
                                                         v
                                      +-------------------------------------+
                                      |      Strata Server (serve/)         |
                                      | • Anthropic / OpenAI API Adapter    |
                                      | • Dynamic KV & fit_max_tokens       |
                                      | • Workspace File & Upload Endpoints |
                                      +-------------------------------------+
                                                         |
                                                         v
                                      +-------------------------------------+
                                      |       C++/HIP Engine (src/)         |
                                      | • 125B MoE Quantized Layers         |
                                      | • VRAM Expert Cache + RAM Offload   |
                                      | • Dedicated NVMe /mnt/data storage  |
                                      +-------------------------------------+
```

### 1. Developer CLI Suites
- **D.L. CLI (`tools/dl_cli.py`):** Purpose-built terminal agent for full-cycle software engineering. Supports interactive plan formulation (`/plan`), one-touch execution switch (`/act`, `/execute`), conversational markdown exporting (`/save`), and built-in diagnostic guardrails.
- **Claude Code CLI Harness:** Routes Anthropic CLI traffic to local Strata with prompt optimizations and dedicated shared workspace directory defaults.
- **DeepSeek CLI (`tools/deepseek_cli.py`):** Interactive terminal client with Rich live layout showing real-time token streaming and reasoning traces.

### 2. Workspace Storage & Remote Web Interface
- **Dedicated Partition:** NVMe storage mounted at `/mnt/data/DL-AI-workspace` shared across all local CLI processes and the Strata web interface.
- **Web Code Integration:** Web-based terminal emulator served via `claude-terminal.service` (ttyd on port 7681) embedded inside the Strata web app (`serve/web/`), allowing remote coding sessions across devices.
- **Workspace File Manager:** Web modal providing tree browsing, multi-file and folder drag-and-drop upload, file attachments to prompt, and secure downloads.

### 3. Safety Guardrails & Local Wiki Integration
- **Auditing Suite:** Automated pre-commit and post-edit checks verifying Python/JS syntax, scanning for accidentally staged credentials, monitoring host CPU/VRAM/RAM pressure, and running targeted tests.
- **Project Wiki:** Embedded project knowledge base (`wiki/`) queried automatically by D.L. CLI and updated via `/wiki` commands.

## Related

- Architecture: [Expert Offloading and Speculation](../concepts/expert-offloading-and-speculation.md)
- Models: [Strata Model Variants](strata-models.md)
- Sizing Decisions: [Model Selection and Hardware Budgeting](../decisions/model-selection-and-hardware-budget.md)
- Deployment: [RX 7600 XT CachyOS Deployment](../decisions/rx-7600-xt-cachyos-deployment.md)
- D.L. CLI Guardrails: [D.L. CLI Auditing and Guardrails Suite](../decisions/dl-cli-auditing-and-guardrails.md)
- DeepSeek Thinking: [DeepSeek CLI Live Thinking Stream](../decisions/deepseek-cli-live-thinking-stream.md)
- Claude Code Integration: [Claude Code CLI Integration on Strata](../decisions/claude-code-cli-integration.md)
- Shared Workspace: [Shared Workspace on Dedicated Storage](../decisions/shared-workspace-d-disk.md)
- Cloudflare Tunnel: [Cloudflare Tunnel Remote Exposure for Strata](../decisions/cloudflare-tunnel-remote-exposure.md)
- GitHub Fork: [GitHub Fork and Public Sanitization Architecture](../decisions/github-fork-and-sanitization.md)
- Upstream Integration: [Strata v0.1.41 Upgrade Walkthrough](../artifacts/strata-v0-1-41-upgrade-walkthrough.md)
- Releases: [Strata Release Milestones](../concepts/strata-release-milestones.md)
- [Shared CLI Session Daemon for Web and Terminal](../decisions/shared-cli-session-daemon.md)
- [Cloudflare Access Login Replaces the API Key](../decisions/cloudflare-access-login-auth.md)
- [D.L. AI Implementation Plan (2026-10-13)](../artifacts/dl-ai-2026-10-13-implementation-plan.md)
- [Antigravity Change Requests, 5-12 Oct 2026](../artifacts/antigravity-change-requests-2026-10.md)
- [Strata Full Project Audit Report (2026-10-16)](../artifacts/strata-full-project-audit-2026-10-16.md)

## Sources

1. `README.md` — project overview and architecture.
2. `AGENTS.md` — guidelines and developer harnesses.
3. `tools/dl_cli.py` — D.L. CLI implementation.
4. `tools/deepseek_cli.py` — DeepSeek CLI implementation.
5. `serve/server.py` — server endpoints and workspace storage APIs.
6. `serve/web/` — web application and terminal integration.
7. User, chat, 2026-10-13.
