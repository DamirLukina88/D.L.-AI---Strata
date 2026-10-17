---
title: "D.L. CLI Auditing and Guardrails Suite"
type: decision
description: "Autonomous guardrails and diagnostic tools integrated into D.L. CLI for syntax checking, secret scanning, telemetry, diffs, and targeted tests."
status: active
tags: [dl-cli, auditing, security, guardrails, testing, telemetry]
created: 2026-10-11
updated: 2026-10-13
last_verified: 2026-10-11
---

# D.L. CLI Auditing and Guardrails Suite

## Summary

Autonomous background guardrails and proactive diagnostic tools integrated into `tools/dl_cli.py` and `tools/dl_auditing.py`. Prevents syntax corruption and credential leakage on file writes, provides real-time hardware budgeting (RAM, Swap, ROCm VRAM), performs semantic git diff auditing, and executes targeted unit tests.

- 2026-10-13: Added an approval gate for destructive commands and out-of-workspace writes (dl_auditing.classify_command / classify_write), and new scan_secrets patterns (environ.get defaults, shell ${KEY:-...}, ctx7sk- keys). See [Approval Gate for Destructive Agent Actions](destructive-action-approval-gate.md).

## Context & Motivation

When the local model (Qwen3.8-Flash-Next Coder) edits code or refactors large files, subtle syntax errors, accidental API key inclusions, or heavy tests can disrupt development. Providing both **active pre-write guardrails** (intercepting `write_to_file` and `replace_file_content`) and **explicit agent tools + slash commands** allows both autonomous prevention and manual developer auditing.

## Implementation Details

### 1. The 5 Core Auditing Tools (`tools/dl_auditing.py`)

1. **`syntax_guard`**:
   - Parses AST for Python (`ast.parse`), JSON (`json.loads`), Node.js (`node --check`), Bash (`bash -n`), and YAML.
   - Runs in-memory before file writes. If invalid syntax is detected, blocks write and provides line/column error feedback allowing self-correction.
2. **`scan_secrets`**:
   - High-confidence regex and entropy scanner for OpenAI keys (`sk-...`), Anthropic (`sk-ant-...`), GitHub PATs (`ghp_...`), AWS keys (`AKIA...`), HuggingFace tokens (`hf_...`), private key blocks, and hardcoded secrets.
   - Blocks writes if credential tokens are found. Masked error feedback guides developer/agent to `wiki/private/.env` or environment variables.
3. **`system_health`**:
   - Zero-overhead `/proc/meminfo` and `/sys/class/drm/card1/device/mem_info_vram_used` sysfs reader for instantaneous RAM, Swap, and ROCm GPU VRAM telemetry (<0.2ms latency).
   - Formats a 79-column Strata dark-and-orange Unicode telemetry card with CPU 1-min load averages and Strata engine context size.
4. **`git_diff_audit`**:
   - Semantic git diff inspector that reviews modified files, deletions, critical infrastructure files (`AGENTS.md`, `.gitignore`, `server.py`), and flags security leaks in added lines.
5. **`smart_test_runner`**:
   - Universal targeted test runner. Inspects git modified files or explicit paths, discovers matching test files (`tools/test_*.py`, `test_*.py`, `*.test.js`), and executes them with `pytest` / `unittest` / `npm test` / `make test`.

### 2. Dual-Layer Integration

- **Autonomous Pre-Write Guardrails**: Intercepts `tool_write_to_file` and `tool_replace_file_content` in `tools/dl_cli.py`. If `syntax_guard` or `scan_secrets` flags a violation, the file on disk remains completely untouched and an error message is returned to the model prompt loop so it can self-correct immediately.
- **Agent Tools (`DL_TOOLS` & `DL_PLAN_TOOLS`)**: All 5 tools are exposed as first-class schemas in both Act and Plan modes.
- **Interactive Slash Commands (`interactive_loop`)**:
  - `/health` or `/sys`: Displays the hardware telemetry card.
  - `/diff` or `/audit`: Runs semantic git diff audit.
  - `/secrets` or `/scan [path]`: Scans codebase or file for leaked credentials.
  - `/syntax <path>`: Runs AST validation on file.
  - `/test [files]`: Runs targeted unit tests.

## Verification & Testing

- Unit tests in `tools/test_dl_auditing.py` verify all AST parsers, secret scanners, hardware metrics, and write-blocking behavior (11 tests in 0.17s).
- CLI standalone flags: `python3 tools/dl_auditing.py --health`, `--diff`, `--secrets`, `--test`.

## Related Decisions

- [Dynamic Workspace Switching and Coupled Local Wiki in D.L. CLI](dynamic-workspace-switching-and-wiki-coupling.md)
- [Pruned Core 6 Tools and 8-Hour JIT Keep-Alive for Local LLM](pruned-core-6-tools-and-8h-keepalive.md)
- [Approval Gate for Destructive Agent Actions](destructive-action-approval-gate.md)
- [D.L. CLI Agent Quality Plan (from the TETRIS test)](../artifacts/dl-cli-agent-quality-plan.md)
- [D.L. CLI On-Demand MCP Loading Plan](../artifacts/dl-cli-on-demand-mcp-plan.md) (the outgoing credential filter)

## Sources

1. User, chat, 2026-10-11.
2. `tools/dl_auditing.py`
3. `tools/dl_cli.py`
4. `tools/test_dl_auditing.py`
5. User, chat, 2026-10-13.
