---
title: "Cloudflare Tunnel Remote Exposure for Strata"
type: decision
description: "Architecture and configuration for exposing Strata Web GUI and API via Cloudflare Tunnel on custom domain."
status: active
tags: [strata, cloudflare, tunnel, remote-access, web-gui]
created: 2026-10-10
updated: 2026-10-13
last_verified: 2026-10-10
---

# Cloudflare Tunnel Remote Exposure for Strata

## Summary
The local Strata server (`http://localhost:8080`) is exposed securely to the internet using an existing Cloudflare Tunnel (`f0a42e7d-ef64-4da4-b529-c18759d79830`) under the user's custom domain at `https://ai.damir-lukina.com` (and `https://strata.damir-lukina.com`). This enables remote access to both the interactive Web GUI and OpenAI/Anthropic-compatible APIs from phones, laptops, and remote developer environments without opening router ports or exposing home IP addresses.

- 2026-10-13: Browsers behind Cloudflare Access no longer need the API key: the server verifies the Access JWT itself. See [Cloudflare Access Login Replaces the API Key](cloudflare-access-login-auth.md). The ttyd /code/ path is gone; the Code tab uses /api/code/session (SSE) instead.

## Decisions & Configuration

### 1. Ingress Routing (`~/.config/cloudflared/config.yml`)
- The tunnel ingress rules route incoming traffic for `ai.damir-lukina.com` and `strata.damir-lukina.com` directly to `http://localhost:8080`.
- Ingress specification:
  ```yaml
  ingress:
    - hostname: ai.damir-lukina.com
      service: http://localhost:8080
      originRequest:
        connectTimeout: 30s
        noTLSVerify: true
    - hostname: strata.damir-lukina.com
      service: http://localhost:8080
      originRequest:
        connectTimeout: 30s
        noTLSVerify: true
    - service: http_status:404
  ```

### 2. Standalone Binary & Systemd User Service
- Installed standalone `cloudflared` binary to `~/.local/bin/cloudflared`.
- Created user systemd unit `~/.config/systemd/user/cloudflared.service` to maintain persistent, encrypted connections to nearest Cloudflare edge data centers (Vienna / Zagreb).

### 3. Strata Reverse Proxy & Host Header Compatibility
- Strata's `server.py` natively permits Cloudflare Tunnel Host headers whenever an API key is configured (`api_key` in `strata-coder-iq1_m.json`), bypassing internal DNS-rebinding restrictions.
- All remote API completions require `Authorization: Bearer <STRATA_API_KEY>`.

### 4. Remote Client Usage
- **Web GUI:** Available at `https://ai.damir-lukina.com/` (interactive browser chat).
- **Remote Claude Code CLI (e.g. from laptop):**
  ```bash
  export ANTHROPIC_BASE_URL="https://ai.damir-lukina.com"
  export ANTHROPIC_AUTH_TOKEN="<STRATA_API_KEY>"
  claude
  ```
- **Remote OpenAI Compatibility:** Endpoint at `https://ai.damir-lukina.com/v1/chat/completions`.

## Related
- [Strata](../entities/strata.md)
- [Claude Code CLI Integration on Strata](claude-code-cli-integration.md)
- [RX 7600 XT CachyOS Deployment](rx-7600-xt-cachyos-deployment.md)
- [Cloudflare Access Login Replaces the API Key in the Web App](cloudflare-access-login-auth.md)

## Sources
- **Agent:** Antigravity (Gemini)
- **Session ID:** 44aeb44c-4179-41a4-b503-f0e55de2e0a8
- **Date:** 2026-10-10
1. User, chat, 2026-10-13.
