---
title: "Web App Split View: Code | Monitor"
type: decision
description: "From 1200 px wide the Code tab and Monitor sit side by side with a draggable divider; narrower screens keep the tabs"
status: active
tags: [web-app, layout, monitor, code-tab]
created: 2026-10-27
updated: 2026-10-27
last_verified: 2026-10-27
---

# Web App Split View: Code | Monitor

## Summary

User decisions, 2026-10-27: at 1200 px and wider the web app shows Code on the left and Monitor on the right; the tabs then pick the right pane (Monitor or About, which opens over Monitor) and the Code tab button is hidden. The divider is dragged with mouse or touch (pointer events), limited to 25-75 %, remembered per browser in localStorage strata.splitPct; double-click, Enter or Home resets 50/50, arrow keys move it 2 %. Below 1200 px (phones, tablets) the tabs work as before. Narrow panes use container queries for the Monitor grids, since the viewport media queries see the wide window. The code stream stays connected while Code is visible in either mode (shown('code') replaced tab === 'code'). The breakpoint is re-checked on window resize too, because the Chromium device emulation fired neither the media-query change nor resize. Files: serve/web/index.html, app.css, app.js.


- 2026-10-27 (later): in a narrow Code pane the bar's session line (ACT, AUTO, YOLO, MCP chips, folder) ran under the buttons. `codeBarFit()` in app.js now measures it in its one-row form and adds `code-terminal-bar--stacked` when it would be cut, so the line gets its own row under "CLI" and the buttons, and moves back up when there is room (a fixed width threshold could not work: the line's length changes with the plan and MCP chips). The class only has CSS from 901 px up; phones keep their own layout.
## Sources

1. User, chat, 2026-10-27: CLI | Monitor side by side on wide displays with a draggable separator; answers: 1200 px, remember per browser, About over the Monitor side.
