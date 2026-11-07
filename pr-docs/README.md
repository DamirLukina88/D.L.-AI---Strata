# Strata Upstream Pull Request & Contribution Packages

This directory contains prepared pull request submissions, verification benchmarks, and ready-to-submit documentation for **[Niko1221/Strata](https://github.com/Niko1221/Strata)**.

---

## 1. High-Impact Pull Request Ready to Open Now

### [PR #5485: Cloudflare Access Zero-Trust JWT Authentication](https://github.com/Niko1221/Strata/pull/5485)
* **Status**: **Open on Upstream** ([PR #5485](https://github.com/Niko1221/Strata/pull/5485))
* **Impact**: Eliminates browser API key exposure when accessing Strata remotely behind Cloudflare Tunnels via signed JWT verification. Zero external dependencies.
* **Branch**: `feat/cloudflare-access-auth` (pushed to `origin`, commit `1b17f88c`)
* **Tests**: 7/7 unit tests passing in `serve.test_cf_access`, 30/30 security tests passing in `serve.test_security`
* **Direct PR Link**: **[https://github.com/Niko1221/Strata/pull/5485](https://github.com/Niko1221/Strata/pull/5485)**
* **Documentation**: [`feat-cloudflare-access-auth.md`](feat-cloudflare-access-auth.md).

### [Community Benchmark: AMD Radeon RX 7600 XT 16 GB (gfx1102), Linux, Ryzen 5 3600](community-benchmark-rx-7600-xt.md)
* **Status**: **Submitted — [PR #5486](https://github.com/Niko1221/Strata/pull/5486)** (Open)
* **Impact**: Provides maintainers with official baseline RDNA3 community benchmarks on ROCm 7.2.4 under zero-swap constraints (`MemorySwapMax=0`).
* **Branch**: `pr/community-benchmark-rx-7600-xt` (`4219bff0`, pushed to `origin`)
* **PR Link**: **[https://github.com/Niko1221/Strata/pull/5486](https://github.com/Niko1221/Strata/pull/5486)**
* **PR Description Markdown**: [`community-benchmark-rx-7600-xt.md`](community-benchmark-rx-7600-xt.md).

### [Issue #5460: Single Model Retrieve Endpoint (`GET /v1/models/{model_id}`)](issue-5460-model-retrieve.md)
* **Status**: **Genuinely Missing in Upstream Main** (Open Issue [#5460](https://github.com/Niko1221/Strata/issues/5460))
* **Impact**: Unblocks **Visual Studio 2026 BYOK (Bring Your Own Key)** custom-OpenAI models and other spec-following clients.
* **Branch**: `pr/issue-5460-model-retrieve` (pushed to `origin`)
* **Tests**: 6/6 tests passing in `serve.test_server.ModelAliases`
* **Direct PR Link**: **[Open PR on GitHub](https://github.com/Niko1221/Strata/compare/main...DamirLukina88:D.L.-AI---Strata:pr/issue-5460-model-retrieve?expand=1)**
* **PR Description Markdown**: Copy from [`issue-5460-model-retrieve.md`](issue-5460-model-retrieve.md).

---

## 2. Issue Comment / Benchmark Verification to Close Issue

### [Issue #4677: AMD RDNA3 Benchmark for `serve_stop_bound`](comment-issue-4677-amd-verification.md)
* **Status**: Upstream merged the code in `243fdb21`, but **maintainer Niko1221 requested community benchmark validation on AMD cards** with speculative decode before closing.
* **Impact**: Provides Niko with the exact measured numbers and 2,736 passing unit test cases needed to close Issue [#4677](https://github.com/Niko1221/Strata/issues/4677).
* **Comment Text**: Copy directly from [`comment-issue-4677-amd-verification.md`](comment-issue-4677-amd-verification.md) and paste as a comment on [Issue #4677](https://github.com/Niko1221/Strata/issues/4677).

---

## 3. Status of Earlier Ported Issues (Already Merged Upstream)

The code changes for these issues were integrated upstream in releases `v0.2.10`, `v0.2.11`, and `v0.2.12`:

| Issue # | Upstream Merge Commit | Status & Release |
| :---: | :---: | :--- |
| **[#4622](https://github.com/Niko1221/Strata/issues/4622)** | `75acfca3` | Part 1 (`undeclared_tool_calls` switch) merged in **v0.2.12** |
| **[#4701](https://github.com/Niko1221/Strata/issues/4701)** | `3bbf0f39` | Merged in **v0.2.11**; verified working today by community |
| **[#4677](https://github.com/Niko1221/Strata/issues/4677)** | `243fdb21` | Merged in **v0.2.10**; awaiting benchmark comment above to close |
| **[#4350](https://github.com/Niko1221/Strata/issues/4350)** | `e1b27d54` | Merged in **v0.2.10** (fatal GPU error exit code 3 + restart) |
| **[#4751](https://github.com/Niko1221/Strata/issues/4751)** | `68ab15dd` | Merged in **v0.2.11/v0.2.12** (tool prefixes) |
| **[#4077](https://github.com/Niko1221/Strata/issues/4077)** | `01d6f7b9` | Merged in **v0.2.8+** (stray think tags) |
