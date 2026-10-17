---
title: Tetris Single-File Plan
type: artifact
description: Architecture plan for a modern neon single-file Tetris game generated via Claude Code on Strata.
status: active
tags: [game, tetris, html, plan, claude-code]
created: 2026-10-10
updated: 2026-10-10
last_verified: 2026-10-10
---

# Tetris — single-file HTML/CSS/JS

## Context

Test in a series: the user wants a Tetris game built the same way as the Snake game — one self-contained `.html` file with inline CSS and JS, no external assets, playable in any browser. Visuals feature modern dark background and neon-colored tetrominoes.

## Chosen defaults (from user's answers)

| Decision | Choice |
|---|---|
| Visual style | Modern dark + neon (cyan/red/purple/blue/green/yellow/orange per piece) |
| Controls | WASD + arrows hybrid — `A`/`←` left, `D`/`→` right, `W`/`↑` rotate CW, `S`/`↓` soft drop, `Space` hard drop |
| Extras | Ghost piece + levels with speed-up. **No** next-piece preview, **no** hold/swap |

## Target File

`/home/damirl/tetris.html` — one file, ~300 lines.

## Structure

```
tetris.html
├── <style>
│   ├── page: dark bg (#0e0e12), centered flex layout
│   ├── playfield: 10×20 grid, subtle border, faint grid lines
│   ├── side panel: score / level / lines (neon text)
│   └── glow: box-shadow on filled cells for the neon look
├── <div> markup: wrapper → canvas + HUD panel
└── <script>
    ├── constants: COLS=10, ROWS=20, CS=24 (canvas 240×480)
    ├── board: Uint8Array(ROWS*COLS) storing color index 0=empty
    ├── tetromino defs: 7 shapes × 4 rotation states, each a list of [x,y] offsets
    │   I, J, L, O, S, T, Z — standard SRS-lite (no wall kicks)
    ├── piece state: {type, rot, x, y}
    ├── gravity: setInterval(tickMs) where tickMs = max(80, 800 - level*70)
    ├── input: keydown → move/rotate/soft-drop/hard-drop; ignore invalid
    ├── collision: bounds + board overlap
    ├── lock: write piece cells into board, then clearLines()
    ├── clearLines: scan rows, splice full rows, shift down, add score
    ├── level: every 10 lines → level++, recompute tickMs
    ├── ghost: project piece down until collision, draw as outline
    └── game over: any new piece spawns already colliding → stop loop
```

## Rendering

Canvas 2D, one `<canvas>` 240×480. Each filled cell drawn as a rounded rect with a 1 px inset gap and a `shadowBlur` glow in the piece's color. Ghost piece drawn as a 1 px stroke outline at 40% alpha.

## Controls

- `A` / `←` — move left
- `D` / `→` — move right
- `W` / `↑` — rotate CW
- `S` / `↓` — soft drop (one cell per press, gravity still applies)
- `Space` — hard drop (snap to ghost position, lock immediately)
- `R` — restart after game over

## Verification

1. Open `file:///home/damirl/tetris.html` in a browser, or `python3 -m http.server 8000 --directory /home/damirl` → `http://localhost:8000/tetris.html`.
2. Confirm: pieces spawn at top-center, fall at level-1 speed, rotate cleanly, stack correctly, full rows clear and shift the stack down, score/level/lines HUD updates, ghost piece shows the landing spot, hard drop locks instantly, game over triggers when the stack reaches the top, `R` restarts.
3. Confirm: no console errors, no external requests.

## Sources
- **Tool:** Claude Code CLI (powered by local Strata Qwen3.8 Coder)
- **Original Path:** `~/.claude/plans/interview-me-frolicking-river.md`
- **Session Date:** 2026-10-10
