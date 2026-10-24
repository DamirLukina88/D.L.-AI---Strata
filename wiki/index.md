---
title: "Wiki Index"
type: index
description: "Entry point and topic map"
status: active
tags: [meta, navigation]
created: 2026-10-05
updated: 2026-10-05
last_verified: 2026-10-05
---

# Wiki Index

Every page in this wiki is listed below. The list is generated; do not edit between the markers.

<!-- index:start -->

## Concepts

- [Expert Offloading and Speculative Decoding](concepts/expert-offloading-and-speculation.md) — Tiered MoE offloading and speculative drafting mechanism in Strata
- [Reference Claude Fable 5.1 and Opus 5.5 System Prompts](concepts/reference-claude-fable-and-opus-prompts.md) — Full archive of Claude Code CLI Fable 5.1 and Opus 5.5 system prompts for architectural reference.
- [Reference DeepSeek System Prompts and Modes](concepts/reference-deepseek-prompts-and-modes.md) — Archival reference of DeepSeek system prompts, /fim (Fill-In-the-Middle), and /prefix mode directives.
- [Strata Release Milestones](concepts/strata-release-milestones.md) — Key features and milestones across Strata releases up to v0.1.41

## Decisions

- [Approval Gate for Destructive Agent Actions](decisions/destructive-action-approval-gate.md) — D.L. CLI asks before destructive commands or writes outside the workspace; /yolo disables per session; content never restricted
- [Auto Thinking Level (/effort auto)](decisions/auto-thinking-level.md) — Default /effort auto: rules pick none/low/med/high per turn, raise on failures, GUI switch in Sampling drawer, replaces manual voice toggle
- [Claude Code CLI Integration on Strata](decisions/claude-code-cli-integration.md) — How Claude Code CLI routes to local Strata with fit_max_tokens while isolating Claude Desktop.
- [CLI Chat Markdown Export Feature](decisions/cli-chat-markdown-export.md) — Parity export feature for saving CLI conversations as structured Markdown via /save slash command and Web Code toolbar button.
- [CLI Graphical Styling & Thinking Defaults](decisions/cli-graphical-styling-and-thinking-defaults.md) — Harmonization of CLI terminal interfaces and Web Code view with Strata dark and orange aesthetic, and default thinking effort configuration.
- [Cloudflare Access Login Replaces the API Key in the Web App](decisions/cloudflare-access-login-auth.md) — Web app trusts a verified Cloudflare Access JWT instead of a browser-stored API key; /v1 clients keep the key
- [Cloudflare Tunnel Remote Exposure for Strata](decisions/cloudflare-tunnel-remote-exposure.md) — Architecture and configuration for exposing Strata Web GUI and API via Cloudflare Tunnel on custom domain.
- [D.L. CLI Auditing and Guardrails Suite](decisions/dl-cli-auditing-and-guardrails.md) — Autonomous guardrails and diagnostic tools integrated into D.L. CLI for syntax checking, secret scanning, telemetry, diffs, and targeted tests.
- [D.L. CLI Keeps Its Task: Trim Protection, PLAN.md, Memory Files, Finish Checks](decisions/dl-cli-task-memory-and-finish-checks.md) — Why the CONTRA run lost its task to trimming (2026-10-19) and the fix: protected user messages, PLAN.md, project_memory, finish checks
- [DeepSeek CLI Live Thinking Stream](decisions/deepseek-cli-live-thinking-stream.md) — Real-time streaming display of reasoning/thinking tokens in DeepSeek CLI with dual Live panels and history preservation.
- [Desktop Piper Voice Switching and STT-Only Auto-Speak Gating](decisions/desktop-piper-voice-switching-and-stt-auto-speak.md) — Resolves Speech Dispatcher generic module quoting for Piper TTS, Chromium Linux voice keys, and gates auto-speak to STT voice prompts only
- [Dynamic Workspace Switching and Coupled Local Wiki in D.L. CLI](decisions/dynamic-workspace-switching-and-wiki-coupling.md) — Adds /cd command and switch_workspace tool to D.L. CLI with automatic wiki binding to the active working directory.
- [GitHub Fork and Public Sanitization Architecture](decisions/github-fork-and-sanitization.md) — Architecture for publishing customized Strata fork to GitHub while preventing credential leakage
- [Home Assistant Core Deployment and Strata MCP Integration](decisions/home-assistant-strata-mcp.md) — Home Assistant Core on D disk (/mnt/data), systemd boot service, and Strata stdio MCP server for smart home control
- [Lazy Loading and GUI Force Restart](decisions/lazy-loading-and-gui-force-restart.md) — Implementation of JIT model loading on request, GUI force restart button, and model selection
- [Local Whisper Speech-to-Text (STT) Integration](decisions/local-whisper-speech-to-text.md) — Implements 100% offline, local Whisper STT via whisper.cpp and MediaRecorder for Desktop Brave and all browsers
- [Model Selection and Hardware Budgeting](decisions/model-selection-and-hardware-budget.md) — Hardware requirements and sizing heuristics for Strata deployments
- [Multimodal Media Pipeline Bridge](decisions/multimodal-media-pipeline-bridge.md) — Routes attached images, video keyframes, rendered PDF pages, audio Whisper transcriptions, and blocks raw binaries in D.L. CLI and session daemon
- [Pruned Core 6 Tools and 8-Hour JIT Keep-Alive for Local LLM](decisions/pruned-core-6-tools-and-8h-keepalive.md) — Reduced LLM prefill tokens by ~65% and set model idle unload to 8 hours to eliminate cold disk reloading.
- [Public Secret Leak and Rotation (2026-10-13)](decisions/secret-leak-rotation-2026-10.md) — Strata, Exa, Context7 and client-IP keys were pushed to the public fork; rotated, moved to secrets.env, history scrubbed
- [Ray: Assistant Name, Female Voice and Persona](decisions/ray-assistant-persona.md) — D.L. AI is now Ray; Piper HFC female voice; casual persona crediting Damir's stack on every Chat request
- [Revert of Struggle Diary and Modular Harness](decisions/revert-struggle-diary-and-modular-harness.md) — Reverted struggle diary telemetry and modular harness files due to prompt bloat, latency overhead, and RAM eviction on reload
- [RX 7600 XT CachyOS Deployment](decisions/rx-7600-xt-cachyos-deployment.md) — Deployment configuration for the RX 7600 XT on CachyOS, and how to start and stop it (strata.sh)
- [Scheduled Jobs in D.L. AI](decisions/dl-ai-scheduled-jobs.md) — The session daemon runs prompts or one exact pre-approved action at a time or on repeat; model warm-up, retries, catch-up, notices
- [Sensitive File Guardrail and Prefix Mode in D.L. CLI](decisions/sensitive-file-guard-and-prefix-mode-in-dl-cli.md) — Prevents credential leaks via @file injection and suppresses conversational chatter using assistant seed prefixes.
- [Shared CLI Session Daemon for Web and Terminal](decisions/shared-cli-session-daemon.md) — One D.L. CLI agent session in dl-ai-sessiond, used from the web Code tab and dl_cli.py --attach; replaced ttyd + tmux scraping
- [Shared Workspace on Dedicated Storage](decisions/shared-workspace-d-disk.md) — Architecture, path mapping, and web integration for shared /mnt/data/DL-AI-workspace across Claude Code CLI and web app.
- [Strata v0.1.43 Performance Switches and Memory Hygiene](decisions/strata-v0-1-43-performance-and-memory-optimizations.md) — Activation of adaptive tier memory overlap, resident RAM soft-commit, and Linux page cache release on exit
- [Weather Reasoning Benchmark for CLI Thinking Levels](decisions/weather-reasoning-benchmark.md) — Standalone benchmark tools/weather_reasoning_bench.py evaluating CLI thinking levels with location inference, table quality, and Proton Mail.

## Preferences

- [Local-Only Repository](preferences/local-only-repository.md) — This Strata checkout is never published to git; local branches and commits are only safety copies

## Entities

- [Strata](entities/strata.md) — High-performance local AI workstation combining 125B MoE inference engine, D.L. CLI, DeepSeek live thinking, and web code terminal
- [Strata Model Variants](entities/strata-models.md) — Model quantizations, specialized variants, and memory footprints supported by Strata

## Artifacts

- [Adaptive Reasoning Evolution Plan](artifacts/adaptive-reasoning-evolution-plan.md) — Implementation plan for tiered reasoning budget caps, empirical evaluation matrix, and CPU semantic router.
- [Antigravity Change Requests, 5-12 Oct 2026](artifacts/antigravity-change-requests-2026-10.md) — The user's 92 change requests to Antigravity for Strata/D.L. AI, newest first; the last three were left unfinished
- [Async Queue Debugging Benchmark Plan (not built)](artifacts/async-queue-debugging-benchmark-plan.md) — Planned harder D.L. CLI benchmark (17 Oct): a multi-file async pipeline bug whose root cause is in channel.py; not built as of 2026-10-20
- [Claude Code On-Demand Strata Walkthrough](artifacts/claude-code-on-demand-walkthrough.md) — Walkthrough of integrating Claude Code CLI with local Strata on-demand lifecycle and signal traps.
- [Claude Code Web Terminal Integration Plan](artifacts/claude-code-web-terminal-integration-plan.md) — Architecture and implementation plan for embedding an authenticated, persistent Claude Code CLI web terminal into the Strata web application.
- [Codebase Audit & Security Remediations Walkthrough](artifacts/codebase-audit-walkthrough.md) — Step-by-step walkthrough of codebase audit findings, security hardening, file descriptor fixes, and test validations across Strata.
- [Codebase Audit Report (Antigravity /boost)](artifacts/codebase-audit-report.md) — Comprehensive architectural, security, and performance audit report for D.L. AI — Strata covering server handlers, proxy, and test suites.
- [Component 1: RDNA3 WMMA Hardware Validation & Dual-Tier Benchmark Report](artifacts/v0-1-45-component-1-wmma-hardware-validation-report.md) — Empirical validation and dual-tier benchmark comparing native WMMA tensor cores against non-WMMA fallback on AMD Radeon RX 7600 XT
- [Component 2: HIP FP32 Tiled QSA Scorer Validation & Benchmark Report](artifacts/v0-1-45-component-2-simt-qsa-scorer-report.md) — Implementation, numerical verification, and dual-tier benchmark for upstream commit 4f21be87 (STRATA_SELECT_SIMT=1) on AMD Radeon RX 7600 XT
- [Component 3: Automatic Thinking Budget Protection Validation & Benchmark Report](artifacts/v0-1-45-component-3-thinking-budget-protection-report.md) — Implementation, unit test verification, and live API stress-testing for upstream commit d0e990ba and 194c2688 (Thinking Budget Protection #984)
- [Component 4: Prompt Tokenizer Prefix Caching Validation & Benchmark Report](artifacts/v0-1-45-component-4-tokenizer-prefix-caching-report.md) — Implementation, bitwise verification, and dual-tier benchmark for upstream commit f13a870d (Prompt Tokenizer Prefix Caching #567 / #1852)
- [Component 5: Web Monitor & Observability Updates Validation Report](artifacts/v0-1-45-component-5-web-monitor-observability-report.md) — Validation of upstream e69cbfa5 (reasoning_effort False) and a091cdf6 (windowed Prometheus throughput gauges #2341)
- [CONTRA Goal Loop and Review Tooling (2026-10-20/21)](artifacts/contra-goal-loop-2026-10-21.md) — The 30-minute Claude loop that reviewed and fixed around the D.L. AI's CONTRA run: rules, review script, browser check, notes sent
- [D.L. AI Implementation Plan (2026-10-13)](artifacts/dl-ai-2026-10-13-implementation-plan.md) — Plan for secret rotation, upstream v0.1.43.1, Access login, zip download, approvals, shared CLI session, README
- [D.L. AI Plan (2026-10-13): Shared Session, Guardrails, README](artifacts/dl-ai-2026-10-13-plan-session-guardrails-readme.md) — Phases 2, 5 and 6 of the 2026-10-13 plan: shared CLI session daemon, approval guardrails, README rewrite
- [D.L. CLI Agent Quality Plan (from the TETRIS test)](artifacts/dl-cli-agent-quality-plan.md) — Plan to make D.L. CLI's agent finish its work and back its claims: turn cap, evidence check, reviewer, tests, browser check, plan files
- [D.L. CLI On-Demand MCP Loading Plan](artifacts/dl-cli-on-demand-mcp-plan.md) — Plan: one small mcp tool lets D.L. CLI load Fetch, Playwright, Google (Gmail/Drive/Docs) and translation MCP servers only when needed
- [D.L. CLI Task Memory and Finish Checks Plan (2026-10-19)](artifacts/dl-cli-task-memory-plan-2026-10-19.md) — Approved plan after the CONTRA run lost its task: trim protection, PLAN.md on approval, memory files in the prompt, done check, wiki schema
- [Engine Port Check Scripts (2026-10-21)](artifacts/engine-port-check-scripts-2026-10-21.md) — The greedy answer check, A/B bench wrapper and streamed-timings check used to verify the 0.2.2 engine port on the RX 7600 XT, plus the serve tests that already failed before it
- [GitHub Fork Sanitization and Push Plan](artifacts/github-fork-sanitization-and-push-plan.md) — Security plan and execution details for sanitizing credentials and publishing the custom Strata fork to GitHub.
- [Google Workspace MCP Live Setup for D.L. CLI](artifacts/google-workspace-mcp-live-setup.md) — How Gmail, Drive and Docs run in D.L. CLI: workspace-mcp, the gmail/drive/docs split, approvals, token, credential filter
- [Harness² Research and Feasibility Analysis for Ray](artifacts/harness2-research-and-tradeoffs-analysis.md) — Analysis of Harness² (arXiv 2610.14224v1, google-research/harness2) method, benchmark numbers, tradeoffs, and architectural fit for Ray.
- [Home Assistant Core and Strata MCP Integration Plan](artifacts/homeassistant-strata-core-plan.md) — Implementation plan: deployment of Home Assistant Core on D disk (/mnt/data), systemd service, and stdio MCP server for Strata smart home control
- [Home Assistant Entity Area Script](artifacts/ha-entity-area-script.md) — Script that lists an HA entity's area and its device's area and moves the entity to another area over the WebSocket API
- [Home Assistant Sensor Units & Smart Outlet Live Power Walkthrough](artifacts/ha-sensor-units-and-outlet-power-walkthrough.md) — Walkthrough of resolving missing units (kWh, kW) on Home Assistant energy/power sensors and adding live outlet power monitoring to Strata MCP
- [Home Assistant Server and Session Tools Walkthrough](artifacts/homeassistant-and-session-tools-walkthrough.md) — Walkthrough of Home Assistant Core deployment, IoT device integration, MCP server, autonomous session tools, and YOLO auto-continue
- [Native Browser STT Implementation Plan](artifacts/native-browser-stt-implementation-plan.md) — Architecture, design specs, and implementation plan for native browser Speech-to-Text (STT) across desktop and mobile browsers.
- [Native Browser STT Implementation Report](artifacts/native-browser-stt-implementation-report.md) — Implementation, push-to-talk, Brave privacy bypass, and verification for native browser Speech-to-Text in App Chat and Code Chat.
- [Native Browser TTS Implementation Plan](artifacts/native-browser-tts-implementation-plan.md) — Architecture, design specs, and implementation plan for native browser TTS in Strata App Chat and Code Chat across desktop and Android browsers.
- [Native Browser TTS Implementation Report](artifacts/native-browser-tts-implementation-report.md) — Implementation, architectural mitigations, and cross-platform verification for native browser Text-to-Speech in Strata App Chat and Code Chat.
- [Ray Persona Bench and Prompt Trim (2026-10-23)](artifacts/ray-persona-bench-2026-10-23.md) — Speaker, address, credit, persona, voice and environment checks for Ray; prompts trimmed 2,598 to 2,295 tokens (CLI), 576 to 429 (Chat)
- [Ray Struggle Diary and Modular Harness Implementation Plan](artifacts/ray-struggle-diary-and-modular-harness-plan.md) — Implementation and validation plan for Ray's operational friction diary and modular harness architecture, enabling human + frontier model refinement.
- [Ray TTS PipeWire Audio Backend and Truncation Fix Report](artifacts/ray-tts-pipewire-and-truncation-fix-report.md) — Resolves PipeWire aplay hangs, 12s pause watchdog interruptions, and natural sentence chunking for Ray Text-to-Speech in Strata Code Chat.
- [Session Commands and Tools Implementation Plan](artifacts/session-commands-and-tools-plan.md) — Implementation plan: autonomous session management tools and conversational continue handling in Strata CLI and Web GUI
- [Shared Workspace Implementation Plan](artifacts/shared-workspace-implementation-plan.md) — Implementation plan for shared workspace directory on dedicated NVMe storage (/mnt/data/DL-AI-workspace) integrated across CLIs and Web UI.
- [Strata / D.L. AI Design Language (visual spec)](artifacts/strata-design-language-spec.md) — Where the 913-line visual spec of the Strata web app lives and what it holds: tokens, components, layouts, porting notes, known gaps
- [Strata AMD Deployment Plan](artifacts/strata-deployment-plan.md) — Tailored deployment plan for Strata on AMD RX 7600 XT (gfx1102) using CachyOS Linux
- [Strata Full Project Audit Report (2026-10-16)](artifacts/strata-full-project-audit-2026-10-16.md) — Comprehensive read-only audit of the Strata / D.L. AI workstation covering C++/HIP engine, Python server, CLI, daemons, test suites, and security.
- [Strata v0.1.41 Upgrade Walkthrough](artifacts/strata-v0-1-41-upgrade-walkthrough.md) — Walkthrough of upgrading the local Strata engine to v0.1.41 while preserving custom MCP tools.
- [Strata v0.1.43 Integration and Optimization Walkthrough](artifacts/strata-v0-1-43-integration-and-optimization-walkthrough.md) — End-to-end integration walkthrough for upstream Strata v0.1.43, HIP recompile on ROCm, UI/CLI preservation, and benchmark optimization matrix
- [Strata v0.1.43 Optimization and Benchmarking Matrix](artifacts/v0-1-43-optimization-benchmark-report.md) — Empirical benchmark evaluation of Adaptive Overlap, Route Tail Skip 7, and Route Resident margin sweeps on AMD RX 7600 XT
- [Strata v0.1.43 Optimization and Benchmarking Plan](artifacts/strata-v0-1-43-optimization-and-benchmarking-plan.md) — Implementation and execution plan for activating runtime optimization switches, benchmarking speedup arms, and tracing MoE expert profiles
- [Strata v0.1.44 Merge (2026-10-13)](artifacts/strata-v0-1-44-merge.md) — Upstream v0.1.44 (2026-10-13) and v0.1.44.1 (2026-10-15) merged into main with our PRs kept; STRATA_COMMIT_BATCH=0 on gfx1102
- [Strata v0.1.44.1 Benchmark Report (2026-10-16)](artifacts/strata-benchmark-2026-10-16.md) — Empirical benchmark evaluation of Strata v0.1.44.1 with Qwen3.8-Flash-Next-Coder-IQ1_M on AMD Radeon RX 7600 XT (ROCm 7.2.4 HIP)
- [Strata v0.1.44.1 Benchmark Report (2026-10-23 Baseline)](artifacts/strata-benchmark-2026-10-23-baseline.md) — Pre-implementation baseline benchmark of Strata v0.1.44.1 on AMD Radeon RX 7600 XT with Qwen3.8-Flash-Next-Coder-IQ1_M.
- [Strata v0.1.45 Complete Upstream Evaluation & Benchmark Report](artifacts/v0-1-45-optimizations-and-tuning-report.md) — Master evaluation, hardware validation, and dual-tier benchmarks for Strata v0.1.45 features on AMD Radeon RX 7600 XT
- [Tetris Single-File Plan](artifacts/tetris-single-file-plan.md) — Architecture plan for a modern neon single-file Tetris game generated via Claude Code on Strata.
- [Uncensored Model Evaluation and Refusal-Direction Projection](artifacts/uncensored-model-evaluation-and-refusal-projection-plan.md) — Hardware evaluation of community uncensored MoE models on 32 GB RAM / 16 GB VRAM and configuration of Strata native refusal-direction projection
- [Unified CLI Architecture & Mobile Companion Feed Walkthrough](artifacts/unified-cli-and-mobile-companion-walkthrough.md) — Walkthrough of consolidating CLI, live slash command syncing, Exa & Context7 chips, and mobile feed ANSI sanitization.
- [Upstream Fork Review (2026-10-13)](artifacts/upstream-forks-review-2026-10-13.md) — Which of Niko1221/Strata's 2,271 forks matter for this install (gfx1102, 32 GB RAM); STRATA_HIP_WMMA and Strata-Cascade are the leads
- [Upstream Open PR Review (2026-10-13)](artifacts/upstream-open-prs-review-2026-10-13.md) — Which open Niko1221/Strata PRs fit this install (gfx1102, 32 GB RAM, Claude Code); all merge cleanly onto main 51fae4a6
- [Upstream PRs Merge Plan (2026-10-13)](artifacts/upstream-prs-merge-plan-2026-10-13.md) — Approved step plan for merging 13 open upstream PRs: backups, merge order, tests, bench-then-enable flag sweep, rollback
- [Upstream Strata 0.2.0-beta and 0.2.1 Review (2026-10-20)](artifacts/upstream-v0-2-releases-review-2026-10-20.md) — Which 0.2.0-beta / 0.2.1 changes fit this install (RX 7600 XT, Linux, 32 GB RAM): most do not apply; the file-tier ports are the one lead
- [Upstream Strata 0.2.2 Review (2026-10-21)](artifacts/upstream-v0-2-2-review-2026-10-21.md) — Which 0.2.2 changes fit this install (RX 7600 XT, Linux, 32 GB RAM, one NUMA node): the HIP verify-hang fix and a few server fixes; most of the release does not apply
- [Upstream Strata 0.2.3 & 0.2.3.1 Review (2026-10-23)](artifacts/upstream-v0-2-3-review-2026-10-23.md) — Upstream 0.2.3 & 0.2.3.1 review (RX 7600 XT): 6 engine/server/vision/web fixes + setup.py archs parser ported; STRATA_HC_Q8=1 enabled after A/B bench
- [Upstream Strata 0.2.4 Review and Hardware Evaluation (2026-10-24)](artifacts/upstream-v0-2-4-review-2026-10-24.md) — Hardware evaluation of Strata 0.2.4 (DeepSeek-V4.1-Flash) on RX 7600 XT (gfx1102), 32 GB RAM, and 274 GB disk; why it cannot run here
- [Upstream Strata v0.1.43 Integration Plan](artifacts/upstream-v0-1-43-integration-plan.md) — Architecture and merge resolution plan for integrating upstream Strata v0.1.43 while preserving custom dark aesthetic, CLI, and guardrails
- [Upstream v0.1.42 Fixes Integration Plan](artifacts/upstream-v0-1-42-fixes-plan.md) — Plan and execution details for integrating upstream Strata v0.1.42 fixes into the custom local installation.
- [Upstream v0.1.45 Enhancements: Evaluation and Dual-Tier Benchmark Plan](artifacts/upstream-v0-1-45-evaluation-and-benchmark-plan.md) — Evaluation, technical spec, validation protocol, and exhaustive dual-tier benchmarks for upstream v0.1.45 on RX 7600 XT

## Logs

- [Wiki Changelog](changelog.md) — Record of every change the agent made to this wiki

## Meta

- [About This Wiki](README.md) — What this wiki is and the rules for agents without the skill

<!-- index:end -->

## Sources

1. Generated by `lint_wiki.py --write-index` from page frontmatter.
