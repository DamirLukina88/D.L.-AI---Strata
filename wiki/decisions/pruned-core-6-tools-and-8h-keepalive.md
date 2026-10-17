---
title: "Pruned Core 6 Tools and 8-Hour JIT Keep-Alive for Local LLM"
type: decision
description: "Reduced LLM prefill tokens by ~65% and set model idle unload to 8 hours to eliminate cold disk reloading."
status: active
tags: [tools, prefill, performance, latency, memory]
created: 2026-10-11
updated: 2026-10-11
last_verified: 2026-10-11
---

# Pruned Core 6 Tools and 8-Hour JIT Keep-Alive for Local LLM

## Summary

Pruned active D.L. CLI tools to 6 core engineering functions (run_command, switch_workspace, view_file, write_to_file, replace_file_content, local_wiki) to cut prefill latency. Background guardrails (AST syntax, secret leaks) run in Python wrapper. Extended idle_unload_s from 1800s to 28800s (8h) in strata-coder-iq1_m.json so 30GB model stays resident in RAM/VRAM.

## Update 2026-10-13

D.L. CLI actually offers 9 tools again (8 when the workspace has no wiki): the 6 core ones plus `exa_web_search`, `resolve_library_id` and `get_library_docs`. More tools now come from MCP servers that are loaded only on demand: see [D.L. CLI On-Demand MCP Loading Plan](../artifacts/dl-cli-on-demand-mcp-plan.md).

## Related Decisions

- [Sensitive File Guardrail and Prefix Mode in D.L. CLI](sensitive-file-guard-and-prefix-mode-in-dl-cli.md)

## Sources

1. User, chat, 2026-10-11.
