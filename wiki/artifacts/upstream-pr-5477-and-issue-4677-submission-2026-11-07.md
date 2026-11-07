---
title: "Upstream Strata PR #5477 and Issue #4677 Submission (2026-11-07)"
type: artifact
description: "Pull Request #5477 (GET /v1/models/{id}), AMD benchmark verification posted to Issue #4677, and audit of upstream v0.2.10-v0.2.12 releases"
status: active
tags: [upstream, pull-request, benchmark, visual-studio-byok, serve-stop-bound, rx7600xt]
created: 2026-11-07
updated: 2026-11-07
last_verified: 2026-11-07
---

# Upstream Strata PR #5477 and Issue #4677 Submission (2026-11-07)

## Summary

On 2026-11-07, an upstream issue audit and contribution session was conducted against **[Niko1221/Strata](https://github.com/Niko1221/Strata)**:
1. **Pull Request #5477 Opened:** Submitted a clean, self-contained pull request implementing `GET /v1/models/{model_id}` in `serve/server.py` to resolve upstream Issue #5460, unblocking Visual Studio 2026 BYOK custom-OpenAI models.
2. **Issue #4677 Benchmark Posted:** Contributed our AMD Radeon RX 7600 XT (`gfx1102`) A/B benchmark numbers and 2,736 passing unit test cases directly to upstream Issue #4677, fulfilling maintainer Niko1221's verification request for the `serve_stop_bound` speculative row commit policy.
3. **Upstream Release Audit (v0.2.10–v0.2.12):** Verified that code fixes for issues #4622, #4701, #4677, #4350, #4751, and #4077 were merged into upstream across recent releases.

---

## 1. Pull Request #5477: Single Model Retrieve Endpoint

* **GitHub PR:** [https://github.com/Niko1221/Strata/pull/5477](https://github.com/Niko1221/Strata/pull/5477)
* **Resolves:** Issue [#5460](https://github.com/Niko1221/Strata/issues/5460)
* **Head Branch:** `DamirLukina88:pr/issue-5460-model-retrieve` (`dd2a60c5`)
* **Base Branch:** `Niko1221:main` (`146df3c4`)

### What Was Changed
- `serve/server.py`:
  - Extended route handling to match paths starting with `/v1/models/` or `/models/`.
  - Added percent-decoding via `unquote`.
  - Matched queried model IDs against active loaded models, aliases, and image generation models, returning individual model objects with HTTP 200.
  - Returns OpenAI-compatible 404 with `{"code": "model_not_found", "param": "model"}` when an unknown model ID is queried.
- `serve/test_server.py`:
  - Added unit test methods `test_model_retrieve_single_and_alias` and `test_model_retrieve_unknown_returns_404`.
  - 6/6 tests passing in `serve.test_server.ModelAliases`.
- **Triage Bot Compliance:** PR description was formatted with exact headings (`## Problem and result`, `## Related discussion`, `## Approach`, `## Validation`, `## Limits`) and verified against `.github/scripts/item-check.js` (`{ ok: true, missing: [] }`).

---

## 2. Issue #4677: Speculative Bounded Commit Validation on AMD Hardware

* **GitHub Comment:** [https://github.com/Niko1221/Strata/issues/4677#issuecomment-6706455058](https://github.com/Niko1221/Strata/issues/4677#issuecomment-6706455058)
* **Issue:** [#4677](https://github.com/Niko1221/Strata/issues/4677)

### Context & Evidence
Maintainer Niko1221 had integrated the speculative decode row-bounding code (`serve_stop_bound`, `243fdb21`), but kept Issue #4677 open awaiting multi-turn continuation verification on AMD hardware.

We posted our 4-leg paired A/B benchmark results from the AMD Radeon RX 7600 XT 16 GB (`gfx1102`, ROCm 6.2, CachyOS Linux, `MemorySwapMax=0`) on `Qwen3.8-Flash-Next Coder IQ1_M` (`--spec 4`, 64K context):
- **Parked Snapshot Rejection Rate:** Dropped from 25.0% (4 of 16 runs rejecting snapshots) to **0.0% (0 of 16 runs rejected)**.
- **Conversation Cache Hit Rate:** Improved from 62.9% to **68.5%**, reducing re-read tokens per session by 94.4% (72 tokens down to 4 tokens).
- **Decode Throughput:** Flat at 24.7 tok/s (within $\pm 0.2$ tok/s noise).
- **Multi-Turn First-Token Latency:** 1.71 s $\rightarrow$ **1.54 s** (10.1% latency improvement).
- **Unit Verification:** 2,736 / 2,736 test cases passing in `tests/core/serve_stop_bound_test.cpp`.

---

## 3. Upstream Status of Earlier Ported Fixes

Cross-referencing `upstream/main` (`146df3c4`) against our fork revealed that code fixes for earlier reported issues have been merged into upstream official releases:
* **#4622**: Part 1 (`undeclared_tool_calls: "text" | "call"` switch) merged in v0.2.12 commit `75acfca3`.
* **#4701**: Closing tag lookahead buffer merged in v0.2.11 commit `3bbf0f39` (community verified on 2026-11-07).
* **#4677**: Engine `serve_stop_bound` merged in v0.2.10 commit `243fdb21`.
* **#4350**: Fatal GPU error exit code 3 + restart merged in v0.2.10 commit `e1b27d54`.
* **#4751**: Tool prefixes (`tools.<name>`, `functions.<name>`) merged in v0.2.11/v0.2.12 commit `68ab15dd`.
* **#4077**: Stray closing think tag line handling merged in commit `01d6f7b9`.

Local PR templates for reference remain preserved in `pr-docs/`.

---

## Related

- [GitHub Fork and Public Sanitization Architecture](../decisions/github-fork-and-sanitization.md)
- [RX 7600 XT CachyOS Deployment](../decisions/rx-7600-xt-cachyos-deployment.md)
- [Upstream Strata v0.2.11 Review and A/B Benchmark (2026-11-05)](upstream-v0-2-11-review-and-benchmark-2026-11-05.md)

---

## Sources

1. GitHub PR #5477: `https://github.com/Niko1221/Strata/pull/5477` (accessed 2026-11-07).
2. GitHub Issue #4677 comment: `https://github.com/Niko1221/Strata/issues/4677#issuecomment-6706455058` (posted 2026-11-07).
3. Upstream Strata commits `dd2a60c5`, `75acfca3`, `3bbf0f39`, `243fdb21`, `e1b27d54`, `68ab15dd`, `01d6f7b9`.
4. User, chat, 2026-11-07 (asked to prepare PR documentation, files, and submit to upstream).
