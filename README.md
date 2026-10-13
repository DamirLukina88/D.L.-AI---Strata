<h1 align="center">D.L. AI</h1>

<p align="center"><b>A private AI workstation built on <a href="https://github.com/Niko1221/Strata">Strata</a></b><br>
Dedicated private AI without external tracking. Your own model, your own rules.</p>

D.L. AI runs the 125-billion-parameter Qwen3.8-Flash-Next Coder model on one desktop PC (an AMD RX 7600 XT with
16 GB and 32 GB of RAM) and turns it into a workstation you can reach from anywhere:

- a coding agent (the **CLI**), with one shared session you can use from the terminal and from the browser
- a chat, a live monitor of the GPU, RAM and engine, and a file workspace on the server
- remote access through a Cloudflare Tunnel, behind a Cloudflare Access login

The inference engine is Strata, unchanged except for configuration. This fork adds the app around it. Upstream
Strata releases are merged as they come out (currently **v0.1.43.1**).

## How fast is it?

Measured on the workstation this fork is built for, with `tools/strata_bench.py` (`bench.sh`):

- **GPU:** AMD Radeon RX 7600 XT, 16 GB (gfx1102, RDNA3), ROCm 7.2 (HIP)
- **RAM:** 32 GB
- **OS:** CachyOS Linux
- **Model:** `qwen3.8-flash-next-coder-iq1_m`, 64K context, int8 KV cache, MTP draft 4

<table>
<tr><td align="center"><b>31.2 tok/s</b><br>peak chat decode</td>
<td align="center"><b>291.7 tok/s</b><br>16K prompt ingestion</td>
<td align="center"><b>1.62 s</b><br>chat time to first token</td>
<td align="center"><b>26.1 tok/s</b><br>coding-agent decode</td></tr>
</table>

Each column adds switches to the one before it:

| Metric | A: baseline | B: + adaptive overlap | C: + route tail skip 7 | D1: + route resident 0.5 | E: + fusions, coding expert profile | F: + RDNA3 switches, core isolation | v0.1.43.1, Arm E config |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Chat decode (median) | 20.0 tok/s | 20.7 | 22.7 | 21.0 | 20.9 (peak 31.2) | 18.4 (peak 28.0) | 18.3 (peak 29.8) |
| Chat time to first token | 2.03 s | 1.93 | 2.13 | 2.03 | 1.86 | 1.81 | **1.62** |
| 4K prompt ingestion | 258.4 tok/s | 265.9 | 264.2 | 268.1 | 268.1 | 265.8 | **277.2** |
| 16K prompt ingestion | 281.8 tok/s | 285.6 | 283.9 | 286.0 | 288.8 | **291.7** | 289.9 |
| 16K time to first token | 57.0 s | 56.3 | 56.6 | 56.2 | 55.7 | **55.1** | 55.4 |
| Agent decode | 22.8 tok/s | 21.5 | 23.8 | **26.1** | 25.9 | 21.3 | 20.2 |
| Agent turn time to first token | 13.3 s | 13.0 | 12.9 | 12.9 | 12.8 | 12.9 | **12.3** |

Numbers are medians over the bench's runs: columns A-F on Strata v0.1.43 (2026-10-11), the last column on
v0.1.43.1 with the Arm E configuration (2026-10-13). Decode medians vary a lot between runs on this card (the
v0.1.43.1 chat runs ranged from 15.9 to 29.8 tok/s), so compare peaks and prompt numbers before decode medians. The configuration in use is
Arm E (`STRATA_ADAPT_OVERLAP=1`, `STRATA_ADAPT_OVERLAP_RESIDENT=1`, `STRATA_ROUTE_TAIL_SKIP=7`,
`STRATA_ROUTE_RESIDENT=0.5` and a custom expert profile built from 12 coding traces with
`tools/make_profile_mix.py`).

## What it adds to Strata

**One CLI session for the browser and the terminal.** The coding agent runs in a small daemon
(`tools/dl_sessiond.py`), not in a terminal window. The web app's **Code** tab and `dl_cli.py --attach` in a
terminal are both clients of the same session, so you can start a task on your phone and continue it at the desk.
The web view is a native page, not a terminal emulator:

- replies render as Markdown
- the model's thinking streams live and folds away
- every tool call is a card you can open
- `/health` draws real bars

**Approvals for destructive actions.** Some actions wait for you to answer Approve or Deny (in either client):

- recursive or forced deletes, `sudo`, and disk tools
- history-rewriting `git` commands
- stopping services or processes
- piping a download into a shell
- removing packages
- anything that writes outside the workspace

`/yolo` turns this off for one session. Content is never restricted.

**Plan mode that can execute.** `/plan` researches read-only and ends with *Execute this plan?*. Answering yes
switches to act mode and runs it.

**Tools for the agent:**

| Tool | What it does |
| :--- | :--- |
| `run_command` | runs a shell command (behind the approval gate) |
| `view_file`, `write_to_file`, `replace_file_content` | read and edit files; writes go through a secret scan and a syntax check |
| `exa_web_search` | web search with Exa |
| `resolve_library_id`, `get_library_docs` | library documentation through Context7 |
| `local_wiki` | the project's knowledge base in `wiki/` |
| `system_health` | GPU, RAM and engine status |
| `git_diff_audit` | reviews the current diff |
| `smart_test_runner` | runs the tests that cover what changed |
| `switch_workspace` | changes the project folder |

**A file workspace on the server.** Upload files by drag and drop, browse them as a folder tree, and use them as
attachments. Downloads stream from disk and can resume, so large archives work on phones too.

**The model loads when you need it.** Nothing is loaded at start. The first request loads the model, and it is
unloaded after 8 hours idle. You can switch between models from the header, and **Force restart** in the monitor
recovers a stuck engine. `STRATA_DROP_CACHE_ON_EXIT=1` gives the page cache (over 20 GB) back when the server
stops.

**Remote access without exposed ports.** A Cloudflare Tunnel publishes the app, and a Cloudflare Access login
protects it. The server verifies the signed Access token on every browser request, so a browser never holds the
API key. API clients (`/v1/*`) keep using the key.

## Install

1. **Install Strata itself** as upstream describes it in [docs/INSTALL.md](docs/INSTALL.md) (on AMD, see also
   [docs/AMD_HIP.md](docs/AMD_HIP.md)). Use `./setup.sh` on Linux and pick the Coder model.

2. **Create the secrets file** `~/.config/dl-ai/secrets.env` (mode 600). Nothing secret is stored in this
   repository:

   ```sh
   STRATA_API_KEY=<a long random string, e.g. python3 -c "import secrets; print(secrets.token_hex(24))">
   EXA_API_KEY=<your Exa key>                 # optional: web search
   CONTEXT7_API_KEY=<your Context7 key>       # optional: library docs
   STRATA_CF_ACCESS_TEAM=<your Zero Trust team name>
   STRATA_CF_ACCESS_AUD=<the Access application's Audience tag>
   ```

3. **Run the server and the session daemon as user services.** Point the server's unit at the secrets file with
   `EnvironmentFile=%h/.config/dl-ai/secrets.env`. Then install the session daemon:

   ```sh
   cp tools/systemd/dl-ai-sessiond.service ~/.config/systemd/user/
   systemctl --user daemon-reload
   systemctl --user enable --now dl-ai-sessiond
   ```

4. **Remote access (optional).** Create a Cloudflare Tunnel to `http://localhost:8080`. Add an Access application
   for its hostname, with a Bypass policy for `/v1/*` if API clients connect from outside. Copy the application's
   **Audience (AUD) tag** into `STRATA_CF_ACCESS_AUD`.

   If you set only the team name, the server logs the tag of the first login it sees, and accepts no Access logins
   until you add it.

5. **Install the secret-scanning commit hook** in your clone:

   ```sh
   ln -sf ../../tools/pre-commit-scan-secrets.py .git/hooks/pre-commit
   ```

## Using it

- **Browser:** open the app (`http://127.0.0.1:8080` locally, or your tunnel hostname). Go to **Code** for the
  agent, **Chat** for plain chat, and **Monitor** for the GPU, RAM and engine.
- **Terminal:** run `python3 tools/dl_cli.py --attach` to join the shared session, and `/detach` to leave it
  running. Without `--attach`, `dl_cli.py` runs a private session as before.
- **Commands** (in either client):

  | Command | What it does |
  | :--- | :--- |
  | `/plan`, `/act` | switch between plan mode and act mode |
  | `/think none\|low\|medium\|high` | set the reasoning effort |
  | `/cd <path>` | change the project folder |
  | `/status`, `/health` | engine status, hardware health |
  | `/exa <query>`, `/context7 <library>` | web search, library docs |
  | `/diff`, `/secrets`, `/test`, `/wiki` | review the diff, scan for secrets, run tests, search the wiki |
  | `/save` | save the chat as Markdown |
  | `/yolo` | turn approvals off for this session |
  | `/clear` | reset the conversation |
  | `!<command>` | run a shell command |

- **API:** the server speaks the OpenAI and Anthropic APIs on `/v1`. Send the key as `Authorization: Bearer`.

## Security

- **No secrets in the repository.** Keys live in `~/.config/dl-ai/secrets.env`, and the pre-commit hook blocks a
  commit that contains one.
- **Browser requests** need a valid Cloudflare Access token (signature, issuer, audience and expiry are checked)
  or the API key. Keys are never accepted in URLs.
- **The session daemon** listens only on a Unix socket in your runtime directory (mode 600).
- **Workspace file access** is confined to the workspace directory.

## Credits and license

Strata, the engine, the server and the installer, is by
[Niko1221 and the Strata contributors](https://github.com/Niko1221/Strata), under the MIT license. This fork keeps
that license ([LICENSE](LICENSE)). Upstream's own documentation is in [docs/](docs/), and its paper is in
[docs/paper](docs/paper).
