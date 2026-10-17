---
title: "Dynamic Workspace Switching and Coupled Local Wiki in D.L. CLI"
type: decision
description: "Adds /cd command and switch_workspace tool to D.L. CLI with automatic wiki binding to the active working directory."
status: active
tags: [dl-cli, workspace, wiki, tools]
created: 2026-10-11
updated: 2026-10-11
last_verified: 2026-10-11
---

# Dynamic Workspace Switching and Coupled Local Wiki in D.L. CLI

## Context

When using D.L. CLI, developers frequently need to switch between repositories or subprojects during an ongoing session without terminating the CLI or losing conversation state. Previously, `workspace` was fixed at process launch, and the agent lacked the capability to change working directory on user prompt. Furthermore, the Local Wiki skill was resolved once at initialization, preventing proper wiki isolation across projects.

## Decision

1. **User Slash & Plain Command (`/cd <path>`, `cd <path>`)**:
   - Implemented in `tools/dl_cli.py` interactive loop.
   - Resolves target path, creates directory if needed, updates process `os.chdir(workspace)`, and dynamically rebuilds the agent's system prompt.
   - Detects whether `<workspace>/wiki` exists, updating active wiki status in memory and UI.

2. **Autonomous Agent Tool (`switch_workspace`)**:
   - Added to `DL_TOOLS` and `DL_PLAN_TOOLS`.
   - Allows the model to autonomously switch project folders upon user request.
   - Uses `session_context` to propagate the updated directory and refresh available tools (`get_active_tools`).

3. **Coupled Local Wiki Lifecycle**:
   - Whenever `/wiki` or `tool_local_wiki` initializes a wiki, it strictly targets `(workspace / "wiki").resolve()` of the currently active working directory.
   - Upon wiki creation or workspace transition, the agent's system prompt is immediately synchronized.

## Sources

1. User request and requirements, chat, 2026-10-11.
2. Commit `883a06ed` (`feat(dl_cli): enable dynamic workspace switching via /cd and switch_workspace tool with coupled wiki initialization`).
