---
title: "Saved CLI Sessions (/sessions, /resume)"
type: decision
description: "/clear and New keep the conversation in dl_sessiond's archive; list, search, rename, delete and resume from the Code tab drawer or the terminal"
status: active
tags: [dl-sessiond, code-tab, web, sessions]
created: 2026-10-27
updated: 2026-10-27
last_verified: 2026-10-27
---

# Saved CLI Sessions (/sessions, /resume)

## Summary

The idea came from upstream 0.2.7's saved chats, which live in the browser for the Chat tab. We removed that tab on 2026-10-23, so here they are built into the session daemon instead. The web Code tab and `dl_cli.py --attach` share one list. Edit, rewind and branch are the planned second step.

## Key Facts

- Storage: `~/.local/state/dl-ai/archive/<session>/<id>.json` (8-hex id; messages, last 3,000 replay events, mode, effort, workspace, plan file) plus `index.json` (title, dates, prompt count). A damaged or missing `index.json` is rebuilt from the files.
- **What saves:** `/clear`, `/reset` and the new `/new` save the current conversation first. The web Code bar's Clear button became **New** (`/new`, no confirm, since nothing is lost). A conversation with no prompts (only `/commands` or `!shell`) is not saved.
- **Resuming** (`/resume N|id`): the current conversation is saved first. The saved one becomes live and leaves the list. Its next `/clear` writes it back under the same id, so there is no second copy. Clients get one `{"type": "restored", "events": [...]}` and redraw it like a replay (web `codeRestored()`, terminal `Renderer`).
- **Title:** the first prompt, cut to 72 characters, unless `/rename` set one. `state` carries `title` and `saved` (the count).
- **Commands** (terminal and web): `/sessions [words]` (newest first; the words must all appear in the title or in a user or assistant message, and a snippet shows where), `/resume N`, `/rename <title>` (this conversation), `/rename N <title>`, `/delete N`. The numbers are always the full list's, also when searching.
- **Delete** moves the file to `archive/<session>/.deleted/<id>-<time>.json`, so it can be recovered.
- **Socket ops** (also allowed through `serve/server.py` `/api/code/session`): `archives` (`query`), `archive_rename` (`id`, `title`) and `archive_delete` (`id`). These work while a turn is running. Resume goes through input (`/resume <id>`), so it is refused while the session is busy.
- **Web:** a Sessions button (layers icon) in the Code bar opens the `#sessions-drawer`: the current conversation (rename), New conversation, search (250 ms debounce), and per row resume (click), rename and delete. The `archives` op is exempt from the stream watchdog's "expect an event back" rule, like `export`.

## Gotchas

- `/save full` reads the transcript since the last `/clear` in `transcripts/<session>/`, so after a resume it does not include the resumed conversation's earlier run.
- The standalone `dl_cli.py` REPL (without `--attach`) does not save on `/clear`; only the daemon does.
- Thinking-block open/closed state is keyed by event seq and is reset on resume.

## Verification (2026-10-27)

- `tools/test_dl_sessiond.py`: 16 tests OK, 3 of them new (`SavedSessions`: save on clear, empty conversation not saved, resume and save back under the same id, search with snippet and full-list numbers, rename both ways, delete to `.deleted`, index rebuild, fields surviving save and load).
- Live, on a throwaway session `sessions-test` (files removed afterwards): a model turn ("PINEAPPLE"), `/new`, `/sessions`, `/resume 1` (10 events redrawn, the answer included), and the HTTP ops through `/api/code/session`.
- Web drawer checked in the built-in browser with stubbed data (the tab had no login): list, search snippet, and rename, delete and resume sending the right ops; screenshot in the dark theme.

## Sources

1. User, chat, 2026-10-27 ("Build saved sessions in dl_sessiond… Leave edit/rewind/branch for a second step").
2. `tools/dl_sessiond.py`, `tools/dl_attach.py`, `serve/web/app.js`, `serve/web/index.html`, `serve/server.py`.
3. Upstream 0.2.7 release notes: `https://github.com/Niko1221/Strata/releases/tag/v0.2.7` (accessed 2026-10-27).
