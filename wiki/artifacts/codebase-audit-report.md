---
title: "Codebase Audit Report (Antigravity /boost)"
type: artifact
status: active
description: Comprehensive architectural, security, and performance audit report for D.L. AI — Strata covering server handlers, proxy, and test suites.
tags: [audit, security, architecture, performance, boost]
created: 2026-10-10
updated: 2026-10-10
last_verified: 2026-10-10
---

# Codebase Audit Report (Antigravity /boost)

**Target:** D.L. AI — Strata (Commit `0a471d8c`)  
**Date:** 2026-10-10  
**Methodology:** Multi-Perspective Antigravity /boost Code & Security Inspection  
**Status:** Completed  

---

## Executive Summary

A comprehensive architectural, security, and performance audit was performed across the entire repository, covering:
1. Python backend server & proxy layers (`serve/server.py`, `serve/frontend.py`, `serve/telemetry.py`).
2. Web application frontend & workspace tree (`serve/web/app.js`, `serve/web/index.html`).
3. Claude Code web terminal & PTY socket tunneling (`tools/run-code-session.sh`, `ttyd` proxy, systemd services).
4. GPU/Host memory budgets on AMD Radeon RX 7600 XT (16 GB VRAM, 32 GB RAM).
5. Automated test suite execution across 593 unit tests and setup suites.

**Overall Health:** **HIGH QUALITY / PRODUCTION READY**  
Zero exposed secrets, zero unauthenticated route leaks. One high-severity path deletion edge case and two minor test/resource warnings were identified and remediated.

---

## Itemized Findings & Remediations

### Finding 1: [HIGH] Workspace Root Deletion Edge Case
* **Component:** `serve/server.py` (`safe_workspace_path` and `do_POST` `/api/workspace/delete`)
* **Vulnerability:** When `/api/workspace/delete` receives an empty path (`""`) or `"."`, `(WORKSPACE_DIR / clean).resolve()` resolves to `WORKSPACE_DIR`. The handler executes `if target.is_dir(): shutil.rmtree(target)`, which would delete the entire workspace root directory.
* **Remediation:** In `safe_workspace_path`, explicitly check if the resolved target matches `WORKSPACE_DIR` and reject it:
  ```python
  def safe_workspace_path(rel_path: str) -> Path | None:
      if not rel_path:
          return None
      try:
          clean = rel_path.lstrip("/\\")
          target = (WORKSPACE_DIR / clean).resolve()
          target.relative_to(WORKSPACE_DIR)
          if target == WORKSPACE_DIR:
              return None
          return target
      except (ValueError, Exception):
          return None
  ```

---

### Finding 2: [MEDIUM] Defense-in-Depth CSRF Protection on Terminal Restart
* **Component:** `serve/server.py` (`do_POST` `/api/code/restart`)
* **Observation:** While `/api/code/restart` requires API key authentication, adding `self._own_page("Claude Code session can be restarted")` ensures cross-origin simple POST requests cannot trigger terminal respawns even if session cookies are present.
* **Remediation:** Add:
  ```python
  if path == "/api/code/restart":
      if not self._own_page("Claude Code session can be restarted"):
          return
  ```

---

### Finding 3: [LOW] Unclosed File Descriptors in Telemetry Polling
* **Component:** `serve/telemetry.py` (lines 264, 283)
* **Observation:** CPU telemetry reads `/proc/cpuinfo` and `/proc/stat` using `open(path).read()` without `with` context managers. In long-running background threads or under Python 3.14, uncollected file handles emit `ResourceWarning` noise.
* **Remediation:** Wrap file reads in `with open(...) as f:` context blocks.

---

### Finding 4: [INFO] Upstream Telemetry Test Drift
* **Component:** `serve/test_server.py` (`AmdTelemetry.test_readings`)
* **Observation:** Recent upstream telemetry additions introduced PCIe link bandwidth metrics (`pcie_gbps`) not accounted for in mocked unit tests.
* **Remediation:** Update test assertions to include upstream keys.

---

## Performance & VRAM Audit (RX 7600 XT, 16 GB VRAM)

* **Architecture Baseline:**
  * Context Window: 65,536 tokens (`--max-context 65536`)
  * KV Quantization: 8-bit (`--kv int8`)
  * Reserve: `--vram-reserve-mib 2560` (providing 3,736 expert cache slots, 7.12 GiB cache, and ~1.38 GiB safe free headroom)
* **Prefill Tuning:**
  * CPU prefill expert sharing active: `STRATA_PREFILL_CPU_SHARE="auto"`
  * Extended prefill chunk size: `--prefill auto:16384`
* **Prompt Caching:**
  * Prompt cache capacity: `--prompt-cache 12`
  * System prompt token countdown pinning: `<total_tokens>` pinned to `15000000 tokens left` to preserve 100% byte-identical cache hits on Turn 2+.

---

## Related
- [Codebase Audit Walkthrough](codebase-audit-walkthrough.md)
- [Claude Code CLI Integration](../decisions/claude-code-cli-integration.md)
- [Strata](../entities/strata.md)

## Sources
- Antigravity (/boost)
- Session ID: 44aeb44c-4179-41a4-b503-f0e55de2e0a8
- Date: 2026-10-10
