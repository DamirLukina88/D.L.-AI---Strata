---
title: "Sensitive File Guardrail and Prefix Mode in D.L. CLI"
type: decision
description: "Prevents credential leaks via @file injection and suppresses conversational chatter using assistant seed prefixes."
status: active
tags: [security, credentials, guardrails, prefix-mode, dl-cli]
created: 2026-10-11
updated: 2026-10-11
last_verified: 2026-10-11
---

# Sensitive File Guardrail and Prefix Mode in D.L. CLI

## Summary

Adopted DeepSeek-style sensitive file detection (blocking .env, .pem, id_rsa, .git-credentials) in D.L. CLI file references. Added /prefix interactive command to seed assistant turns with code blocks, eliminating preamble banter.

## Sources

1. User, chat, 2026-10-11.
