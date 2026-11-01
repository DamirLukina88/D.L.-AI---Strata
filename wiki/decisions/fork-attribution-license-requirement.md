---
title: "Fork Attribution Requirement in MIT License"
type: decision
description: "Forks and derivative works must credit upstream Strata and D.L. AI - Strata"
status: active
tags: [license, legal, github, fork]
created: 2026-11-01
updated: 2026-11-01
last_verified: 2026-11-01
---

# Fork Attribution Requirement in MIT License

## Summary

The repository license (`LICENSE`) was updated from standard MIT to an MIT License with an explicit Attribution Requirement. Any fork, redistribution, or derivative work of this repository must prominently credit both:
1. **Upstream Strata** ([Niko1221/Strata](https://github.com/Niko1221/Strata)) and its contributors for the core inference engine, architecture, and original platform development.
2. **D.L. AI - Strata** ([DamirLukina88/D.L.-AI---Strata](https://github.com/DamirLukina88/D.L.-AI---Strata)) and Damir Lukina for the fork development, features, and modifications.

## Background & Rationale

- Originally, the repository inherited upstream Strata's standard MIT License (`Copyright (c) 2026 Niko1221 and the Strata contributors`), without explicit copyright or attribution terms covering the customized fork's development (Ray persona and animations, D.L. CLI, voice pipeline, shared session daemon, Home Assistant MCP, and performance optimizations).
- The user instructed that any fork of our repository must credit both Strata and our repository for the development.
- The update preserves upstream copyright notices and MIT terms while adding the fork's copyright notice and a clear attribution requirement in repository documentation (README), license notices, and user-facing documentation or graphical interfaces.

## Changes

- `LICENSE`: Added copyright notice for Damir Lukina and the D.L. AI - Strata contributors, and added the Attribution Requirement clause.
- `README.md`: Updated the Credits and license section to reflect the MIT License with Attribution Requirement and specify fork credit requirements.
- `docs/HOW_IT_WORKS.md`: Updated license section.
- `docs/DETAILS.md`: Updated credits and license note.

## Related

- [GitHub Fork and Public Sanitization Architecture](github-fork-and-sanitization.md)
- [Local-Only Repository](../preferences/local-only-repository.md)

## Sources

1. User, chat, 2026-11-01.
