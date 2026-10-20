---
title: "Strata / D.L. AI Design Language (visual spec)"
type: artifact
description: "Where the 913-line visual spec of the Strata web app lives and what it holds: tokens, components, layouts, porting notes, known gaps"
status: active
tags: [design, ui, web-app, css, reference]
created: 2026-10-20
updated: 2026-10-20
last_verified: 2026-10-20
---

# Strata / D.L. AI Design Language (visual spec)

## Summary

`~/Desktop/Strata-Design-Language.md` (50,537 bytes, 913 lines, dated 2026-10-13 20:01) is a complete visual spec of the web app in `/mnt/data/Strata/serve/web/`. It was written so a coding agent can restyle another app (React, Vue or Svelte) to match. It is taken from the real source files: `tokens.css` (design tokens, dark and light), `components.css` (the `st-` UI kit), `app.css` (layout, chat, monitor, dialogs, responsive rules), `sprite.svg` (33 duotone icons) and `fonts/` (Outfit variable font, OFL). It is kept on the Desktop, not copied here, because of its length; which tool wrote it is not recorded, and it is not in Antigravity's transcripts *(checked 2026-10-20)*.

## What it holds

1. The look in one paragraph, plus seven design principles: a near-black blue-grey background (`#0b0d10`), surfaces in two steps, 1px hairline borders instead of heavy shadows, **one** accent (orange `#f97316`) for primary, active and "you", the Outfit type face with 900 weights for brand and hero numbers, 8/14/20 px corners, a 4 px grid, 160 ms motion, status shown as dot + tint, tabular numbers.
2. Design tokens to copy verbatim. 3. Base styles. 4. Components (CSS and markup). 5. Page layouts. 6. Responsive rules. 7. JavaScript behaviours. 8. Porting to React / Vue / Svelte. 9. Do / Don't.
10. Known gaps in the source: `app.css` uses tokens that `tokens.css` never defines (`--st-muted` → `--st-ink-muted`, `--st-surface-1` → `--st-surface`, `--st-fw-semibold` → 600, `--st-fw-normal` → 400), and a few dark-only `rgba(...)` washes look wrong in the light theme.

## Notes

- The spec describes the web app as of 2026-10-13. Later UI changes (the STT/TTS controls, the Code-tab plan chip of 2026-10-20) are not in it.
- The unknown-token gap is a real CSS issue in `serve/web/app.css`, independent of porting.

## Related

- [CLI Graphical Styling & Thinking Defaults](../decisions/cli-graphical-styling-and-thinking-defaults.md) - the same dark and orange look in the CLI

## Sources

1. `~/Desktop/Strata-Design-Language.md`, sections 1 and 10 read 2026-10-20.
