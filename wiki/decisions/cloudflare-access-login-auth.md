---
title: "Cloudflare Access Login Replaces the API Key in the Web App"
type: decision
description: "Web app trusts a verified Cloudflare Access JWT instead of a browser-stored API key; /v1 clients keep the key"
status: active
tags: [auth, cloudflare, security, web-gui]
created: 2026-10-13
updated: 2026-10-13
last_verified: 2026-10-13
---

# Cloudflare Access Login Replaces the API Key in the Web App

## Summary

- 2026-10-13: On a new device the app demanded the API key even after the Cloudflare Access login. serve/cf_access.py now verifies the Cf-Access-Jwt-Assertion header (RS256 against https://damirl.cloudflareaccess.com/cdn-cgi/access/certs, cached 1 h; issuer, AUD, exp/nbf) with the standard library only, and _authorized() in serve/server.py accepts a valid login from the loopback tunnel connector in place of the key - even when the browser still sends an old, wrong key. GET /api/whoami tells the page; it then hides the key field and clears any stored key.
- Rejected: the server handing the key to the page as a cookie (the key would still reach every browser).
- Config in ~/.config/dl-ai/secrets.env: STRATA_CF_ACCESS_TEAM=damirl and STRATA_CF_ACCESS_AUD. With only the team set, the server logs the AUD of the first correctly signed login and accepts none (discovery mode).
- The ?token= / ?key= URL credential and the strata_key cookie were removed (keys in URLs leak into logs); downloads use single-use tickets instead. /v1/* still bypasses Access and needs the key.
- 2026-10-13 (later): Enabled. The AUD was discovered from the user's first login and set in secrets.env; the server logs 'Cloudflare Access logins from https://damirl.cloudflareaccess.com are accepted in place of the API key'.

## Sources

1. User, chat, 2026-10-13.
