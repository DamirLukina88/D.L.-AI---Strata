---
title: "Cloudflare Access Login Replaces the API Key in the Web App"
type: decision
description: "Web app trusts a verified Cloudflare Access JWT instead of a browser-stored API key; /v1 clients keep the key"
status: active
tags: [auth, cloudflare, security, web-gui]
created: 2026-10-13
updated: 2026-11-07
last_verified: 2026-11-07
---

# Cloudflare Access Login Replaces the API Key in the Web App

## Summary

- 2026-10-13: On a new device the app demanded the API key even after the Cloudflare Access login. serve/cf_access.py now verifies the Cf-Access-Jwt-Assertion header (RS256 against https://damirl.cloudflareaccess.com/cdn-cgi/access/certs, cached 1 h; issuer, AUD, exp/nbf) with the standard library only, and _authorized() in serve/server.py accepts a valid login from the loopback tunnel connector in place of the key - even when the browser still sends an old, wrong key. GET /api/whoami tells the page; it then hides the key field and clears any stored key.
- Rejected: the server handing the key to the page as a cookie (the key would still reach every browser).
- Config in ~/.config/dl-ai/secrets.env: STRATA_CF_ACCESS_TEAM=damirl and STRATA_CF_ACCESS_AUD. With only the team set, the server logs the AUD of the first correctly signed login and accepts none (discovery mode).
- The ?token= / ?key= URL credential and the strata_key cookie were removed (keys in URLs leak into logs); downloads use single-use tickets instead. /v1/* still bypasses Access and needs the key.
- 2026-10-13 (later): Enabled. The AUD was discovered from the user's first login and set in secrets.env; the server logs 'Cloudflare Access logins from https://damirl.cloudflareaccess.com are accepted in place of the API key'.
- 2026-10-20, gotcha: Log out did not log out. The button only opened the app's `GET /cdn-cgi/access/logout` endpoint, which ends this app's `CF_Authorization` cookie (HttpOnly: page JavaScript cannot clear it). But the Access session on the team domain stayed valid and silently signed the app in again on the next visit. Fix (`serve/web/app.js`): call the app logout in the background, then open `https://damirl.cloudflareaccess.com/cdn-cgi/access/logout` (moves on after 3 s at most). The URL comes from `serve/web/site-config.js` (`window.STRATA_LOGOUT_URL`), a machine file kept out of git like the other Access settings and served from disk, so no restart is needed. Tested locally with a stand-in URL; the user tests the real logout. An identity provider (Google, GitHub) may still remember the user, which is its own session.
- 2026-11-05, gotcha: a non-browser client with the correct API key still gets HTTP 401 from Cloudflare on `/api/*` (`server: cloudflare`, `invalid_token`), not from Strata; only `/v1/*` passes. The Android app's native calls must use `/v1` paths; see [Ray Hybrid WebView Companion](ray-hybrid-webview-companion-and-phone-mcp.md).
- 2026-11-07: Submitted upstream Pull Request #5485 (`[Engine] serve: Cloudflare Access zero-trust JWT authentication (STRATA_CF_ACCESS_TEAM)`) and backported 3 security/robustness audit fixes (`58be0d3d`) into local Ray (`main`): (1) `_foreign_page()` in `serve/server.py` now checks `self._given_key()` rather than `svc.api_key` so ambient `CF_Authorization` browser cookies remain protected by `Origin` and `Content-Type: application/json` CSRF checks; (2) `AccessVerifier._key()` in `serve/cf_access.py` tracks `_last_attempt` to throttle failed JWK certificate refreshes by `REFETCH_MIN` (60s); and (3) `AccessVerifier.verify()` checks `isinstance(header, dict)` before `header.get("alg")`. All 10/10 local tests in `serve/test_cf_access.py` and 23/23 in `serve/test_security.py` passed.

## Sources

1. User, chat, 2026-10-13.
