---
title: "Shared Workspace on Dedicated Storage"
type: decision
description: "Architecture, path mapping, and web integration for shared /mnt/data/DL-AI-workspace across Claude Code CLI and web app."
status: active
tags: [workspace, storage, web, claude-code, api]
created: 2026-10-10
updated: 2026-10-10
last_verified: 2026-10-10
---

# Shared Workspace on Dedicated Storage

## Summary
To enable a seamless project folder shared between local terminal development (via Claude Code CLI) and remote web app access (`https://ai.damir-lukina.com/`), a dedicated workspace directory is created on the 1 TB NVMe secondary drive (`/mnt/data/DL-AI-workspace`, D disk).

## Decisions & Configuration

### 1. Storage Location & Permissions
- **Host Path:** `/mnt/data/DL-AI-workspace`
- **Ownership & Mode:** `damirl:damirl` with permissions `0755`.
- **Disk:** Dedicated 1 TB NVMe partition mounted at `/mnt/data` (277 GB free).

### 2. Claude Code CLI Default Folder
- **Behavior:** The `claude()` shell function in `~/.bashrc` automatically defaults its working directory:
  ```bash
  if [ "$PWD" = "$HOME" ]; then
      cd /mnt/data/DL-AI-workspace || true
  fi
  ```
  Whenever Claude Code is launched from the user's home directory or without an explicit folder argument, it operates inside `/mnt/data/DL-AI-workspace`.

### 3. Web App Storage & API Endpoints
The Strata server (`serve/server.py`) exposes authenticated endpoints with strict path traversal validation (`safe_workspace_path` ensuring paths stay strictly within `WORKSPACE_DIR`):
- `GET /api/workspace/files`: Lists files, sizes, modified dates, and MIME classifications.
- `POST /api/workspace/upload`: Saves files directly to `/mnt/data/DL-AI-workspace`.
  - **Duplicate Policy:** Overwrites existing files automatically.
- `GET /api/workspace/download?file=<name>`: Streams binary downloads with `Content-Disposition: attachment`.
- `GET /api/workspace/file?file=<name>`: Returns file content (UTF-8 text or base64 image data URL) for immediate prompt attachment.
- `POST /api/workspace/delete`: Deletes files from the workspace.

### 4. Web GUI Integration
- **Server Workspace Button:** The orange folder icon (`#workspace-btn`) in the composer bar opens the Server Workspace modal. To prevent browser SVG sprite caching desyncs on mobile, the icon is inlined directly as SVG.
- **Hidden Redundant Attach Button:** The old local paperclip button is hidden from the UI (`hidden`, `display: none !important`) while preserving underlying code.
- **Mobile Touch vs Desktop Drag & Drop:** Mobile smartphone browsers (iOS / Android) do not support OS-level cross-app file drag-and-drop into browser viewports. To provide a seamless mobile experience:
  - The dropzone is fully tap-interactive: tapping anywhere inside the dropzone triggers the device's native file / camera picker (`ws-file-input.click()`).
  - Dropzone text adapts ("Tap here or drop files to upload to D:\DL-AI-workspace").
  - On desktop, drag-and-drop into the dropzone or dialog uploads files directly.
- **Actions:** Each file has one-click "Attach to prompt", "Download", and "Delete" controls. Fullscreen responsive layout on mobile screens (`max-width: 600px`).
- **Cache Invalidation:** `Cache-Control: no-cache, no-store, must-revalidate` is enforced for `serve/web/` and root HTML, paired with asset query versioning (`?v=20261010-5`).

### 5. Folder Hierarchy & Collapsible Subsections
- **Recursive Directory Upload:** On modern desktop browsers, dropping whole directories uses `webkitGetAsEntry()` / `createReader()` to traverse all files recursively. Each file is uploaded with its relative subpath in `X-Filename: relative/sub/path.txt` so the directory structure is preserved inside `/mnt/data/DL-AI-workspace`.
- **Collapsible File Management UI:** In the workspace modal, files residing in subdirectories are grouped automatically into collapsible folder rows:
  - Each directory displays a folder icon, directory name, item count badge (e.g. `3 files`), and toggle chevron (`▶` / `▼`).
  - Expanding a folder reveals its indented children with individual attach, download, and delete actions.
  - Subfolders can be collapsed or expanded independently so complex folder trees do not clutter the workspace table.

### 6. Path Validation, Symlink Escapes & CSRF Protection
To prevent directory traversal, symlink escapes, CSRF tampering, and accidental workspace root deletion:
- `safe_workspace_path` strips leading slashes, resolves the target path, and verifies `target.relative_to(WORKSPACE_DIR)`.
- It explicitly checks `if target == WORKSPACE_DIR: return None` to prevent malicious or malformed requests (e.g. `file=""` or `file="."`) from targeting or deleting the root `/mnt/data/DL-AI-workspace` directory.
- `GET /api/workspace/files` guards directory traversal against symlinks pointing outside the workspace via `resolved.is_relative_to(WORKSPACE_DIR)` and handles unreadable/broken symlinks gracefully.
- `POST /api/workspace/delete` enforces `self._own_page()` (CORS preflight & JSON requirement) and `POST /api/workspace/upload` enforces `self._foreign_origin()` checks to prevent cross-origin CSRF attacks from external sites in the browser.

## Related
- [Claude Code CLI Integration on Strata](claude-code-cli-integration.md)
- [Cloudflare Tunnel Remote Exposure for Strata](cloudflare-tunnel-remote-exposure.md)
- [Strata](../entities/strata.md)

## Related

- [Shared Workspace Implementation Plan](../artifacts/shared-workspace-implementation-plan.md) — Implementation details for shared workspace directory on dedicated NVMe storage.

## Sources
1. `/home/damirl/.bashrc` lines 27-56
2. `serve/server.py` workspace endpoints and `safe_workspace_path`
3. `serve/web/app.js` and `serve/web/index.html` workspace modal implementation

