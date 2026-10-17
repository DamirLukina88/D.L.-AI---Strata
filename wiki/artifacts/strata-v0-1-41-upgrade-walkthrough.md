---
title: Strata v0.1.41 Upgrade Walkthrough
status: active
tags: [strata, upgrade, walkthrough, mcp]
created: 2026-10-10
updated: 2026-10-10
last_verified: 2026-10-10
type: artifact
description: Walkthrough of upgrading the local Strata engine to v0.1.41 while preserving custom MCP tools.
---
# Walkthrough: Upgrading Strata to v0.1.41

## Goal
The goal of this task was to update the local Strata repository (running on an AMD RX 7600 XT `gfx1102` setup) to the latest upstream version, **v0.1.41**, while preserving our custom MCP tools for local coding generation and review.

## Changes Made
1. **Identified Upstream Rebases:** `origin/main` had advanced to `v0.1.41`, and importantly, the upstream maintainers had officially incorporated support for `gfx1102`.
2. **Discarded Obsolete Work:** Because `gfx1102` is now supported natively, we discarded our local `setup.py` patch with `git restore setup.py`.
3. **Backed Up and Reapplied MCP Additions:**
   - Saved a `.patch` of our additions to `tools/strata_mcp.py` (which injects the `strata_coder_generate` and `strata_coder_review` tools).
   - Executed `git reset --hard origin/main` to absorb `v0.1.41` cleanly and resolve diverged commits safely (as per `wiki/preferences/local-only-repository.md`).
   - Ran `patch -p1 < /tmp/strata_mcp.patch` to re-insert our MCP tools into the freshly updated `strata_mcp.py`.
4. **Recompiled the Engine:**
   - We observed that running `./strata.sh start` continued to use the old `v0.1.39` engine binary because `engine/strata` wasn't re-compiled.
   - We ran `setup.py` using the virtual environment (`/mnt/data/Strata/.venv/bin/python setup.py --setup --yes ...`) to rebuild the HIP engine with the `v0.1.41` features (such as `STRATA_PREFILL_CPU_SHARE`).
5. **Restarted the Service:** The newly compiled engine started on port `8080`.

## Validation Results
- Verified that `git log -1` confirms `HEAD` is exactly on `v0.1.41`.
- Verified `strata_status` MCP tool confirms `engine_version: "0.1.41"` and reports it as running and idle.
- Validated our custom `strata_coder_generate` tool by executing it locally (successfully generated a Python snippet in 4.4 seconds).

The Strata Coder is now fully updated and operational!

## Sources
- **Tool:** Antigravity AI Assistant
- **Session ID:** 44aeb44c-4179-41a4-b503-f0e55de2e0a8
- **Date:** 2026-10-10
