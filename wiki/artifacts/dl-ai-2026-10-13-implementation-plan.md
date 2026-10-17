---
title: "D.L. AI Implementation Plan (2026-10-13)"
type: artifact
description: "Plan for secret rotation, upstream v0.1.43.1, Access login, zip download, approvals, shared CLI session, README"
status: active
tags: [plan, security, cli, cloudflare, upstream]
created: 2026-10-13
updated: 2026-10-13
last_verified: 2026-10-13
---

# D.L. AI Implementation Plan (2026-10-13)

## Context

Antigravity stopped on 12 Oct (quota) with three requests unfinished: the zip download, the README rewrite, and the guardrail changes. Since then you asked for three more things:
- a better web CLI that still works in the system terminal (reference: Claude Code Remote Control, "claude rc")
- no API-key prompt on new devices behind Cloudflare Access
- the upstream Strata changes

While exploring I found a live security problem that has to be fixed first. Four secrets are hardcoded and pushed to the **public** fork `DamirLukina88/D.L.-AI---Strata`:
- the Strata API key (`tools/dl_cli.py:82` and `tools/run-code-session.sh`)
- the Exa key (`dl_cli.py:83`)
- the Context7 key (`dl_cli.py:84`)
- `CLIENT_IP_ENCRYPTION_KEY` (`dl_cli.py:85`)

They first landed in commits 82626651, 41d0623d and c928fa0c. `/v1/*` bypasses Cloudflare Access, so anyone holding the Strata key can use your API right now.

Your decisions: shared agent session; trust the Cloudflare login; rotate the keys and rewrite history; approval for destructive commands; plan mode may execute after approval.

Work happens in `/mnt/data/Strata` on a new branch `dl/2026-10-13`. Each phase gets its own commit. Nothing is pushed until Phase 0's history rewrite is done.

---

## Phase 0: Rotate and scrub the leaked secrets (do first)

1. **Remove the secrets from the code.**
   - In `tools/dl_cli.py:82-85`, use `os.environ.get(NAME, "")` with no fallback.
   - In `tools/run-code-session.sh`, drop the `${STRATA_API_KEY:-…}` fallback.
   - Add a small loader `load_env_file()` in `dl_cli.py`. It reads `~/.config/dl-ai/secrets.env` (mode 600), and environment variables override it.
2. **Rotate the keys.**
   - Generate a new Strata API key with `secrets.token_hex(24)`.
   - You regenerate the Exa and Context7 keys in their dashboards; I can't do that.
   - Generate a new `CLIENT_IP_ENCRYPTION_KEY`.
   - Write all four to `~/.config/dl-ai/secrets.env` and to `wiki/private/.env` (`wiki.py env set`).
3. **Stop putting the key in systemd unit files.**
   - Update `~/.config/systemd/user/strata-server.service` and `claude-terminal.service` (the latter is replaced in Phase 2) to use `EnvironmentFile=%h/.config/dl-ai/secrets.env` instead of an inline `Environment=STRATA_API_KEY=…`.
   - Restart the units.
4. **Rewrite history.**
   - Back up first: `git bundle create ~/strata-pre-scrub.bundle --all`.
   - Run `git filter-repo --replace-text` with the four old values mapped to `REDACTED`.
   - Re-add `origin` (filter-repo removes it) and force-push `main`.
   - Then check that GitHub's code search no longer finds the values.
5. Run `tools/test_dl_auditing.py` and `scan_secrets` over the repo, and add a pre-commit hook in `.git/hooks/pre-commit` that runs `scan_secrets` on staged files.

**Needs from you:** the new Exa and Context7 keys, and approval for the force-push.

## Phase 1: Merge upstream v0.1.43.1 (released yesterday, 33 commits)

What's in it that matters to us (RX 7600 XT, HIP, Linux, agentic CLI):

- **Fixes an engine crash on long prompts.** Prompt-loan chunks that can't be lent are now halved instead of ending the engine (af6affb8, 4468e0e6, #2090). This may explain the "hangs on the 2nd larger prompt" problem.
- **Better tool calling.** A JSON tool call inside a Markdown fence in `<tool_call>` is now recovered (de603bb8). A quoted `</tool_call>` inside a message is no longer taken as the end of the call (a6830008). Directly improves the CLI.
- **Watchdog and RAM-pressure fixes.** On a busy file tier, the server no longer kills a long prompt that is paging in (38032f54). Parked conversations report progress (3804b43f). Both fit our 32 GB box.
- **Server API.** A failing `before_load` hook returns 503 with Retry-After, and `/unload?wait=1` is available (c7838c52); our Force-restart button can use it. An engine refusal of a BGEN slot now tries another slot instead of a permanent 400 (c5fa1b58). Picture downloads are cancelled when the client leaves (873a0d66).
- **Prompt path.** Pageable host-to-device copies now go through pinned bounce slots (7bab660b). We'll benchmark this.
- **`STRATA_ADAPT_OVERLAP` is now opt-in on every backend** (661ff293). We already turned it on, and it must stay explicitly set in `run-coder-iq1_m.sh` / `run-q2_0.sh` or we lose the measured gain.
- **Smaller items:**
  - `bench` no longer saves a profile from its own short prompts over yours (017a672a).
  - The bench and monitor name the GPU in use.
  - `setup --calibrate --model` works (6956f605).
- **Not relevant to us:** the gfx103x HIP fix (we're gfx1102), the SYCL changes, and `--batch` with layer split.

Steps:
1. `git merge upstream/main` (tag v0.1.43.1). The only conflicts are in `serve/server.py`, `serve/frontend.py` and `serve/test_frontend.py`. Resolve them the way e2fe7888 did: keep our D.L. AI handlers (workspace, code, auth) and take upstream's engine and tool-call logic.
2. Rebuild HIP in `build-hip` as described in the wiki page `strata-v0-1-43-integration-and-optimization-walkthrough.md`.
3. Run `serve/test_frontend.py`, `serve/test_server.py`, `serve/test_parallel.py` and `tools/test_strata_bench.py`.
4. Bench with `bench.sh` against the wiki baseline (31.2 tok/s decode, 291.7 tok/s 16K prefill). Record the result in the wiki.

## Phases 2, 5 and 6

Moved to [D.L. AI Plan (2026-10-13): Shared Session, Guardrails, README](dl-ai-2026-10-13-plan-session-guardrails-readme.md): the shared agent session for the web CLI and the terminal (Phase 2), guardrails (Phase 5) and the README rewrite (Phase 6).

## Phase 3: No API key on new devices (trust the Cloudflare Access login)

1. New `serve/cf_access.py`, using only the standard library:
   - fetch and cache (1 h) the JWKS from `https://<team>.cloudflareaccess.com/cdn-cgi/access/certs`
   - verify the RS256 signature of the `Cf-Access-Jwt-Assertion` header (PKCS#1 v1.5 with Python ints, no new dependency)
   - check `aud` against `STRATA_CF_ACCESS_AUD`, plus `iss`, `exp` and `nbf`
2. `_authorized()` in `serve/server.py:5046` accepts any one of:
   - the API key, as Bearer or x-api-key (unchanged, for `/v1/*` clients and the CLI)
   - a valid Access JWT
   - **remove** the `?token=` / `?key=` query parameter (it leaks into logs and history) and the `strata_key` cookie
3. New `GET /api/whoami` returns `{auth: "cf-access", email}` or `{auth: "key"}`.
   - `app.js` calls it on load. With `cf-access` it hides the API-key field and sends no Authorization header.
   - Without it, the current key field stays as the fallback for direct LAN access (`127.0.0.1:8080`).
4. Settings go in `secrets.env`: `STRATA_CF_ACCESS_TEAM=damirl` and `STRATA_CF_ACCESS_AUD=<Application Audience tag>`. The tag comes from Zero Trust → Access → Applications → your app; you copy it.
5. Hardening:
   - The JWT is trusted only when the request comes from the cloudflared tunnel (peer 127.0.0.1). The signature check is what actually matters.
   - Keep the `/v1/*` bypass as it is (API key only).
   - Logout keeps using the Access logout URL and clears local storage.

## Phase 4: Fix the large zip download (request 1)

Cause: `/api/workspace/download` (`serve/server.py:5439`) loads the whole file into RAM with `read_bytes()`. The client (`app.js:1739` `downloadFromWorkspace`) then `fetch()`es it into a Blob in browser memory. For the 263 MB `Strata.zip` that fails on mobile Brave and is slow through the tunnel. The header also breaks on non-ASCII filenames.

- **Server:**
  - stream with `shutil.copyfileobj` in 1 MiB chunks
  - `Content-Disposition: attachment; filename="ascii"; filename*=UTF-8''<pct-encoded>`
  - support `Range` / `206` for resume, `Accept-Ranges: bytes` and `Cache-Control: no-store`
- **Client:** replace fetch+Blob with a normal navigation (`<a href="api/workspace/download?file=…" download>`), so the browser's download manager writes straight to disk. With Phase 3, Cloudflare Access cookies authenticate it and there is no key in the URL.
  - LAN fallback (no Access): `POST /api/workspace/download-ticket` returns a single-use ticket that is valid for 60 s and used as `?ticket=`.
- **Test:** add a case to `serve/test_server.py` covering a 300 MB sparse file, a Range request and a non-ASCII name.

## Phase 7: Wiki and wrap-up

Use the local-wiki skill in `/mnt/data/Strata/wiki`:
- new decision pages:
  - Cloudflare Access JWT auth
  - shared agent session architecture
  - destructive-command approval policy
  - secret rotation and history rewrite
- update:
  - the `github-fork-and-sanitization` page
  - the `cloudflare-tunnel-remote-exposure` page
  - `strata` entity
  - the benchmark report
- add a short "Antigravity session ended 12 Oct (quota)" note to the changelog

---

## Verification

- **Secrets:**
  - `git log -p --all | grep -E '<old key prefixes>'` returns nothing
  - the GitHub search for the old key strings returns nothing
  - the old Strata key gets 401 on `https://ai.damir-lukina.com/v1/models`
  - the new key gets 200
- **Upstream:**
  - the serve and setup tests pass
  - `bench.sh` decode and prefill are no worse than the wiki baseline
  - a 20K-token prompt completes without the watchdog stopping it
- **Auth:**
  - log into the app on a fresh browser or the second laptop: no key prompt, `/api/whoami` says `cf-access`
  - `curl` the same origin without a JWT and without a key: 401
  - a forged or expired JWT: 401
- **Shared session:**
  - start a task in the web Code tab on the phone, then `dl-cli attach` in Konsole: the same history and a live stream, and typing in either one shows up in both
  - `/health` renders as HTML on mobile
  - restart `dl-ai-sessiond`: the session is restored
- **Approvals:**
  - ask the model to `rm -rf build-vision` (a scratch copy): an approval card appears on the web and a `y/N` prompt in the terminal, and Deny keeps the files
  - in plan mode, Execute runs the plan
- **Download:**
  - `Strata.zip` (263 MB) downloads on phone Brave and on desktop with progress shown
  - `curl -r 0-99` returns 206
  - a file with a non-ASCII name (e.g. `š.txt`) downloads correctly
- **README:** renders correctly on GitHub, and `scan_secrets` is clean.

**Order:** 0 → 1 → 3 → 4 → 5 → 2 → 6 → 7. Auth and the download fix are small and unblock you quickly. Phase 2 is the largest and builds on the approval events from Phase 5.

## Outcome (2026-10-13)

Executed the same day on branch `dl/2026-10-13`, fast-forwarded into `main` and force-pushed to the fork (`51fae4a6`). Differences from the plan:

- Phase 0: the first filter-repo run also rewrote upstream's GitHub-signed merges and broke the merge base; it was redone with `--refs` limited to our own branches. The user regenerated the Exa and Context7 keys.
- Phase 2: the optional on-demand "Raw shell" (ttyd) toggle was not built; `!<command>` in the session covers shell use, behind the approval gate.
- Phase 3: an AUD discovery mode was added (only the team set: the first signed login logs its AUD). The `?token=` query credential and the `strata_key` cookie were fully removed in a later commit.
- Phase 6: the README benchmark column is the configuration in use (Arm E + F switches), not Arm E alone.
- Follow-ups not in the plan: thinking blocks start open and remember being closed (Chat and Code); memory margins after desktop freezes (see [RX 7600 XT CachyOS Deployment](../decisions/rx-7600-xt-cachyos-deployment.md)).

## Related

- [Public Secret Leak and Rotation](../decisions/secret-leak-rotation-2026-10.md)
- [Cloudflare Access Login Replaces the API Key](../decisions/cloudflare-access-login-auth.md)
- [Shared CLI Session Daemon](../decisions/shared-cli-session-daemon.md)
- [Approval Gate for Destructive Agent Actions](../decisions/destructive-action-approval-gate.md)
- [Antigravity Change Requests, 5-12 Oct 2026](antigravity-change-requests-2026-10.md)

## Sources

1. Claude Code plan file `~/.claude/plans/create-a-implementation-plan-valiant-ladybug.md`, session of 2026-10-13, approved by the user.
