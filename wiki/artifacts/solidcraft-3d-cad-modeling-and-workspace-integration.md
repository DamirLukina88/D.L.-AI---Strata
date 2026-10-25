---
title: "Workstation Expansion: SolidCraft Parametric 3D CAD Modeling Suite for Ray"
type: artifact
description: "Integration of SolidCraft parametric 3D CAD modeling tool for Ray, automatically exporting and saving models to Ray's workspace."
status: active
tags: [mcp, solidcraft, cad, 3d, parametric, step, stl, ray, workspace]
created: 2026-10-25
updated: 2026-10-25
last_verified: 2026-10-25
---

# Workstation Expansion: SolidCraft Parametric 3D CAD Modeling Suite for Ray

## Summary

This update equips Ray (Rei) with a specialized on-demand SolidCraft MCP server ([`tools/solidcraft_mcp.py`](file:///home/damirl/Desktop/Strata/tools/solidcraft_mcp.py)), expanding Ray's catalog to **38 on-demand MCP servers**. All generated CAD models, neutral exchange formats, and GPU-rendered preview snapshots are saved directly into Ray's working directory (`/mnt/data/DL-AI-workspace`).

---

## 1. Official Git Repository Documentation Mapping

All tools, commands, and parameter schemas in Ray's SolidCraft integration correspond directly to the upstream open-source SolidCraft repository:
- **Repository:** [https://github.com/tangency-labs/solidcraft](https://github.com/tangency-labs/solidcraft)
- **Documentation Portal:** [https://docs.solidcraft.io](https://docs.solidcraft.io)
- **MCP Agent Protocol & CLI Engine:** [docs/mcp.md](https://github.com/tangency-labs/solidcraft/blob/main/docs/mcp.md) (covers JSON-RPC 2.0 stdio, `execute`, `batch`, `eval`, `snapshot`, `render`, `allow-any-path`).
- **Desktop Control Channel Protocol:** [docs/control-protocol.md](https://github.com/tangency-labs/solidcraft/blob/main/docs/control-protocol.md) (handshake on `127.0.0.1:7878` or `127.0.0.1:27878` with session token).
- **Core Modeling Capabilities:** [docs/capabilities.md](https://github.com/tangency-labs/solidcraft/blob/main/docs/capabilities.md) & [docs/features.md](https://github.com/tangency-labs/solidcraft/blob/main/docs/features.md).
- **Feature Patterns:** [docs/feature-patterns.md](https://github.com/tangency-labs/solidcraft/blob/main/docs/feature-patterns.md) (rectangular, circular, path patterns).
- **Metric / UNC Thread Catalogue:** [docs/thread-catalogue.md](https://github.com/tangency-labs/solidcraft/blob/main/docs/thread-catalogue.md).
- **GPU Viewport Rendering & Raytracing:** [docs/render-jobs.md](https://github.com/tangency-labs/solidcraft/blob/main/docs/render-jobs.md).
- **Analytical Oracle Benchmark (75 Validated Parts):** [docs/oracle.md](https://github.com/tangency-labs/solidcraft/blob/main/docs/oracle.md).

---

## 2. Capabilities & Architecture

1. **Workspace Hygiene & Persistence (`get_rei_workspace`):**
   - Automatically resolves Ray's working directory from `STRATA_WORKSPACE_DIR` or `/mnt/data/DL-AI-workspace`.
   - All operations atomically save `.solidcraft` project files, `.step` neutral CAD models, `.stl` 3D-printable meshes, and `.png` viewport renders into Ray's workspace.
2. **Parametric Part Generator (`solidcraft_create_part`):**
   - **Enclosures / Boxes:** Parametric electronics housings with custom outer dimensions, uniform wall thickness, rounded corner fillets, and hollowed cavities (`solid.shell`).
   - **Mounting Brackets:** Structural L-brackets with customizable leg dimensions, thickness, root stress-relief fillets, and mounting screw holes.
   - **Flanges / Disks:** Circular mounting flanges with center bore and parametric circular bolt patterns (`solid.pattern.circular`).
   - **Standoffs / Spacers:** Cylindrical or hex standoffs with bolt clearance holes.
3. **Custom Model Execution (`solidcraft_build_model`):**
   - Direct execution of multi-step parametric CAD timelines (`parameters.add`, sketches, dimensions, extrusions, cuts, fillets, chamfers).
   - Generates and saves scripts, models, and exports in a single call.
4. **Model Inspection & Physical Metrics (`solidcraft_inspect_model`):**
   - Runs `solidcraft-cli eval` to verify manifold geometry, total volume ($\text{mm}^3$), surface area ($\text{mm}^2$), bounding box, center of mass, and mass based on material density.
5. **GPU-Accelerated Viewport Snapshots (`solidcraft_render_snapshot`):**
   - Generates high-resolution PNG snapshots using the AMD Radeon RX 7600 XT Vulkan hardware renderer across multiple camera angles (`iso`, `top`, `front`, `section`).
6. **Live GUI Viewport Control (`solidcraft_launch_gui`):**
   - Can launch `solidcraft --control 7878` in the background so the user can interactively watch and inspect the 3D model in the desktop viewport.

---

## 2. Verification & Testing

- `python3 -m py_compile tools/solidcraft_mcp.py` passed with 0 errors.
- Unit test verified automated generation of `rei_test_enclosure`:
  - Created `.solidcraft`, `.step`, `.stl`, and a 900 KB GPU-rendered `.png` in `/mnt/data/DL-AI-workspace`.
  - Bounding box $70 \times 45 \times 25\text{ mm}$, volume $16,512\text{ mm}^3$, 100% manifold with 0 timeline errors.
- Top-view cross-section render verified.
- Registered in `~/.config/dl-ai/mcp.json` with 100% regex trigger precision.

---

## 3. Related Artifacts

- [full-workstation-audit-and-verification-2026-10-25.md](full-workstation-audit-and-verification-2026-10-25.md)
- [davinci-cst-ipc2152-wargaming-and-v026-sync-walkthrough.md](davinci-cst-ipc2152-wargaming-and-v026-sync-walkthrough.md)

---

## Sources

- SolidCraft CAD Engine: `/usr/bin/solidcraft-cli` and `/usr/bin/solidcraft`.
- Ray workspace: `/mnt/data/DL-AI-workspace`.
- Tools: `tools/solidcraft_mcp.py`, `~/.config/dl-ai/mcp.json`.
