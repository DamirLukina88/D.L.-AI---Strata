<h1 align="center">D.L. AI</h1>

<p align="center"><b>A private AI workstation built on <a href="https://github.com/Niko1221/Strata">Strata</a></b><br>
Dedicated private AI without external tracking. Your own model, your own rules.</p>

D.L. AI runs the 125-billion-parameter Qwen3.8-Flash-Next Coder model on one desktop PC (an AMD RX 7600 XT with
16 GB and 32 GB of RAM) and turns it into a workstation you can reach from anywhere:

- a coding agent (the **CLI**), with one shared session you can use from the terminal and from the browser
- **Local Whisper STT & Neural TTS:** hands-free voice dictation with zero cloud data leaks, paired with neural voice read-aloud
- **Home Assistant MCP Server:** direct voice and text control of lights, climate, smart plugs, 3D printers, and camera feeds
- a chat, a live monitor of the GPU, RAM and engine, and a file workspace on the server
- remote access through a Cloudflare Tunnel over QUIC, behind a Cloudflare Access login

The inference engine is Strata, unchanged except for configuration and hardware kernel ports. Upstream
Strata releases are merged as they come out (currently **v0.1.45**).

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

| Metric | A: baseline | B: + adaptive overlap | C: + route tail skip 7 | D1: + route resident 0.5 | E: + fusions, coding expert profile | F: + RDNA3 switches, core isolation | v0.1.43.1 / v0.1.45 config |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Chat decode (median) | 20.0 tok/s | 20.7 | 22.7 | 21.0 | 20.9 (peak 31.2) | 18.4 (peak 28.0) | 18.3 (peak 29.8) |
| Chat time to first token | 2.03 s | 1.93 | 2.13 | 2.03 | 1.86 | 1.81 | **1.62** |
| 4K prompt ingestion | 258.4 tok/s | 265.9 | 264.2 | 268.1 | 268.1 | 265.8 | **277.2** |
| 16K prompt ingestion | 281.8 tok/s | 285.6 | 283.9 | 286.0 | 288.8 | **291.7** | 289.9 |
| 16K time to first token | 57.0 s | 56.3 | 56.6 | 56.2 | 55.7 | **55.1** | 55.4 |
| Agent decode | 22.8 tok/s | 21.5 | 23.8 | **26.1** | 25.9 | 21.3 | 20.2 |
| Agent turn time to first token | 13.3 s | 13.0 | 12.9 | 12.9 | 12.8 | 12.9 | **12.3** |

Numbers are medians over the bench's runs. The active configuration combines Arm E and Arm F: `STRATA_ADAPT_OVERLAP=1`,
`STRATA_ADAPT_OVERLAP_RESIDENT=1`, `STRATA_ROUTE_TAIL_SKIP=7`, `STRATA_ROUTE_RESIDENT=0.5`, fusion and RDNA3 switches,
the gfx1102 SIMT QSA scorer (`STRATA_SELECT_SIMT=1`), core isolation (`STRATA_AUX_CPUS=auto`), and a custom expert profile built
from coding traces with `tools/make_profile_mix.py`.

## What it adds to Strata

### 1. Unified Shared CLI & Autonomous Coding Agent
The coding agent runs in a persistent background daemon (`tools/dl_sessiond.py`). Both the web app's **Code** tab
and `dl_cli.py --attach` in a terminal are clients of the same session, allowing you to start a task on your phone
and seamlessly inspect or continue it from your terminal:
- Native Markdown formatting, folding reasoning streams, and expandable tool cards.
- **Approvals for destructive actions:** recursive deletes, `sudo`, disk tools, git history rewriting, and writes outside workspace require explicit Approve/Deny.
- **YOLO Mode & Infinite Continuation:** `/yolo` disables approval prompts per session and enables infinite autonomous auto-continuation past `DL_MAX_TURNS` for complex workflows.
- **Plan Mode:** `/plan` investigates read-only and presents an *Execute this plan?* prompt to transition cleanly into act mode.
- **Conversational Continues:** naturally typing *"continue"*, *"keep going"*, or *"go on"* routes directly to turn continuation.

### 2. Local Whisper Speech-to-Text (STT) & Hands-Free Auto-Send
Dictate prompts privately with 100% offline speech recognition:
- **Local Whisper Engine:** runs on the PC host via `whisper.cpp` (`ggml-base.bin`) through `POST /v1/audio/transcriptions` with zero cloud leaks.
- **Real-Time Interim Speech:** progressive interim speech population renders in the composer while walking or talking.
- **Dual-Mode Voice Typing:** click to toggle recording, or hold-to-talk with visual recording pulse.
- **Instant Auto-Send (0ms Delay):** hands-free auto-send populates the text field and submits immediately upon speech pause.
- **Mobile Keyboard Suppression:** taps on voice triggers call `navigator.virtualKeyboard.hide()` and set `inputmode="none"`, preventing smartphone on-screen keyboards from obscuring the screen.
- **Browser Speech Fallback:** Web Speech API fallback available when local Whisper is uninstalled.

### 3. Native Browser Text-to-Speech (TTS) & Neural Piper
Listen to responses hands-free without third-party audio streaming:
- **Voice-Gated Auto-Speak:** *"Automatically read new answers aloud"* speaks replies only when the input was dictated via STT, preserving silence when typing.
- **20 US Neural Piper Voices:** high-quality local Piper speech synthesis integrated via Linux Speech Dispatcher and Web Speech API.
- **Natural Speech Cleaner (`cleanForSpeech`):** strips markdown, emojis, code blocks, box borders, and converts math, units, and symbols to natural spoken words.
- **Mobile Keep-Alive & Controls:** Android Screen WakeLock and MediaSession notification drawer controls (play, pause, stop).

### 4. Home Assistant Smart Home MCP Server
A built-in Model Context Protocol (MCP) server (`tools/homeassistant_mcp.py`) exposes your smart home directly to the agent:
- Direct entity control: lights, switches, media players, climate units (Gree AC), covers, and smart plugs.
- Live camera snapshots: captures and saves camera feeds to the workspace for multimodal inspection.
- Jinja2 template rendering and entity state history lookups.
- Interactive MCP tools explorer in the web GUI via `/mcp`.

### 5. Tools for the Agent

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
| `save_chat` | exports the current CLI chat history to structured Markdown |
| `get_system_health`, `get_engine_status` | autonomous machine telemetry and engine diagnostics |
| `clear_conversation` | resets conversation state cleanly |
| `list_entities`, `get_state`, `call_service`, `toggle`, `render_template`, `get_history`, `get_camera_snapshot` | Home Assistant smart home control suite |

### 6. Workspace, JIT Model Loading & Remote Access
- **Server File Workspace:** upload files by drag and drop, browse folder trees, stream and resume large downloads.
- **JIT Model Loading & Memory Hygiene:** models load on demand and unload after 8 hours idle. `STRATA_DROP_CACHE_ON_EXIT=1` returns Linux page cache (20+ GB) immediately on exit.
- **Zero-Port Remote Access:** Cloudflare Tunnel over QUIC publishes the app, authenticated via Cloudflare Access JWT.

## Install

1. **Install Strata itself** as upstream describes it in [docs/INSTALL.md](docs/INSTALL.md) (on AMD, see also
   [docs/AMD_HIP.md](docs/AMD_HIP.md)). Use `./setup.sh` on Linux and pick the Coder model.

2. **Create the secrets file** `~/.config/dl-ai/secrets.env` (mode 600). Nothing secret is stored in this
   repository:

   ```sh
   STRATA_API_KEY=<a long random string, e.g. python3 -c "import secrets; print(secrets.token_hex(24))">
   EXA_API_KEY=<your Exa key>                 # optional: web search
   CONTEXT7_API_KEY=<your Context7 key>       # optional: library docs
   HASS_URL=http://127.0.0.1:8123             # optional: Home Assistant smart home
   HASS_TOKEN=<your Long-Lived Access Token>  # optional: Home Assistant
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

4. **Remote access (optional).** Create a Cloudflare Tunnel to `http://localhost:8080` with QUIC protocol. Add an Access application
   for its hostname, with a Bypass policy for `/v1/*` if API clients connect from outside. Copy the application's
   **Audience (AUD) tag** into `STRATA_CF_ACCESS_AUD`.

5. **Install the secret-scanning commit hook** in your clone:

   ```sh
   ln -sf ../../tools/pre-commit-scan-secrets.py .git/hooks/pre-commit
   ```

## Using it

- **Browser:** open the app (`http://127.0.0.1:8080` locally, or your tunnel hostname).
  - **Code:** shared coding agent with mobile cards and terminal views.
  - **Chat:** voice typing, read-aloud TTS, and attachments.
  - **Monitor:** real-time GPU, VRAM, RAM, and KV cache monitoring.
- **Terminal:** run `python3 tools/dl_cli.py --attach` to join the shared session, and `/detach` to leave it
  running.
- **Commands** (in either client):

  | Command | What it does |
  | :--- | :--- |
  | `/plan`, `/act` | switch between plan mode and act mode |
  | `/yolo` | turn approvals off and enable infinite continuation |
  | `/continue` | continue execution of multi-turn assistant plans |
  | `/think none\|low\|medium\|high` | set the reasoning effort |
  | `/cd <path>` | change the project folder |
  | `/status`, `/health` | engine status, hardware health |
  | `/mcp <server>` | inspect and execute tools on connected MCP servers |
  | `/speak` | read the latest assistant message aloud |
  | `/exa <query>`, `/context7 <library>` | web search, library docs |
  | `/diff`, `/secrets`, `/test`, `/wiki` | review the diff, scan for secrets, run tests, search the wiki |
  | `/save` | save the chat as Markdown |
  | `/clear` | reset the conversation |
  | `!<command>` | run a shell command |

- **API:** the server speaks the OpenAI and Anthropic APIs on `/v1` (`/v1/chat/completions`, `/v1/audio/transcriptions`). Send the key as `Authorization: Bearer`.

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
