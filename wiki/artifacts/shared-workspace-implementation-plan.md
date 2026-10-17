---
title: "Shared Workspace Implementation Plan"
type: artifact
description: "Implementation plan for shared workspace directory on dedicated NVMe storage (/mnt/data/DL-AI-workspace) integrated across CLIs and Web UI."
status: active
tags: [workspace, storage, nvme, cli, web-app]
created: 2026-10-10
updated: 2026-10-11
last_verified: 2026-10-11
---

# Shared Workspace Implementation Plan (`/mnt/data/DL-AI-workspace`)

This plan implements a shared workspace directory on the dedicated storage partition (`/mnt/data/DL-AI-workspace`), tightly integrating the **Claude Code CLI**, **D.L. CLI**, **DeepSeek CLI**, and the **D.L. AI Web App** (`https://ai.damir-lukina.com/`).

---

## Architecture & Data Flow

```mermaid
flowchart TD
    subgraph Storage ["Dedicated NVMe Storage (D: Partition)"]
        WS["/mnt/data/DL-AI-workspace"]
    end

    subgraph CLIs ["Multi-Scaffold CLI Suite"]
        CC["Claude Code CLI"] -->|Reads / Writes| WS
        DL["D.L. CLI"] -->|Reads / Writes| WS
        DS["DeepSeek CLI"] -->|Reads / Writes| WS
    end

    subgraph WebApp ["D.L. AI Web App (https://ai.damir-lukina.com)"]
        UI["Chat Composer & Workspace UI"]
        API["Strata Server Backend (serve/server.py)"]

        UI -->|Upload files & Drag-Drop| API
        UI -->|Browse & Attach files to prompt| API
        UI -->|Download files to browser| API

        API -->|Secure read/write/list with overwrite policy| WS
    end
```

---

## 1. Shared Storage Setup
- **Directory**: `/mnt/data/DL-AI-workspace`
- **Permissions**: `0755`, owned by `damirl:damirl`.
- Directory auto-created on service startup if missing.

---

## 2. CLI Default Integration
- **Target File**: `tools/run-code-session.sh` & user shell configuration.
- **Behavior**:
  - Automatically pins working directory to `/mnt/data/DL-AI-workspace`.
  - All CLIs operate on this shared tree with full read/write access.

---

## 3. Backend Endpoints (`serve/server.py`)
- Authenticated, path-traversal-protected workspace endpoints:
  - `GET /api/workspace/files`: Lists files recursively with relative paths, sizes, and timestamps.
  - `GET /api/workspace/file?path=...`: Retrieves file content.
  - `POST /api/workspace/file`: Creates or updates a file.
  - `DELETE /api/workspace/file`: Deletes a file.

## Sources
- `tools/run-code-session.sh` — Multi-scaffold runner script and working directory configuration.
- `serve/server.py` — Workspace file browser, upload, and deletion API endpoints.
- [Shared Workspace on Dedicated Storage](../decisions/shared-workspace-d-disk.md) — Architecture decision.

