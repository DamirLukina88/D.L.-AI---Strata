<h1 align="center">Ray</h1>

<p align="center"><b>A private AI assistant and coding agent built on <a href="https://github.com/Niko1221/Strata">Strata</a></b><br>
One desktop PC, no cloud model, nothing sent anywhere. Your own model, your own rules.</p>

Ray is a household AI assistant that runs entirely on one desktop PC: the 125-billion-parameter Qwen3.8-Flash-Next
Coder model on an AMD RX 7600 XT with 16 GB, plus 32 GB of system RAM. This fork, by
[Damir](https://github.com/DamirLukina88), adds everything around the engine and makes it a workstation you can
reach from anywhere:

- **Ray**, the assistant: you talk to her and she answers out loud, with a female neural voice and her own casual
  personality. She knows she runs on the home server, not in someone's cloud, and you can reach her from your phone.
- **D.L. CLI**, a coding agent with one shared session you can use from the terminal and from the browser
- **Offline voice:** local Whisper speech-to-text and Piper text-to-speech, with no audio leaving the PC
- **Home Assistant MCP server:** the coding agent switches lights and climate and reads printers and cameras
  (a Gree air conditioner, a Bambu Lab A1 3D printer, Xiaomi cameras, Tuya plugs and sensors)
- a live monitor of the GPU, RAM and engine, and a file workspace on the server
- remote access through a Cloudflare Tunnel over QUIC, behind a Cloudflare Access login

The inference engine is Strata, configured and optimized for AMD RDNA3 (ROCm/HIP). Upstream
Strata releases are continuously evaluated and synced with each release. Upstream 0.2.0-beta and 0.2.1 were
reviewed on 2026-10-20 ([review](wiki/artifacts/upstream-v0-2-releases-review-2026-10-20.md)). From 0.2.2 and 0.2.3/0.2.3.1,
crucial engine, vision, and spec fixes were ported alongside enabling 8-bit hyper-connection weights (`STRATA_HC_Q8=1`)
after an A/B benchmark ([review](wiki/artifacts/upstream-v0-2-3-review-2026-10-23.md)). On 2026-10-25, **v0.2.5** and
**v0.2.6** were synchronized: CommonMark soft linebreaks, direct screenshot clipboard paste (`Ctrl+V`), window-level
drag-and-drop, dynamic model load timeout scaling, safe shard removal guards, `require_messages(messages)` OpenAI-spec
validation, 1-token health check speed guards, and stable GPU hardware telemetry IDs
([v0.2.5 walkthrough](wiki/artifacts/strata-v0-2-5-sync-and-ergonomics-walkthrough.md),
[v0.2.6 & tools walkthrough](wiki/artifacts/davinci-cst-ipc2152-wargaming-and-v026-sync-walkthrough.md),
[system audit](wiki/artifacts/full-workstation-audit-and-verification-2026-10-25.md)).

## How fast is it?

Measured on the workstation this fork is built for, with `tools/strata_bench.py` (`bench.sh`):

- **GPU:** AMD Radeon RX 7600 XT, 16 GB (gfx1102, RDNA3), ROCm 7.2 (HIP)
- **RAM:** 32 GB
- **OS:** CachyOS Linux
- **Model:** `qwen3.8-flash-next-coder-iq1_m`, 64K context, int8 KV cache, MTP draft 4

<table>
<tr><td align="center"><b>32.3 tok/s</b><br>peak decode</td>
<td align="center"><b>334.4 tok/s</b><br>16K prompt ingestion</td>
<td align="center"><b>1.62 s</b><br>chat time to first token</td>
<td align="center"><b>25.9 tok/s</b><br>coding-agent decode</td></tr>
</table>

Each column adds switches to the one before it:

| Metric | A: baseline | B: + adaptive overlap | C: + route tail skip 7 | D1: + route resident 0.5 | E: + fusions, coding expert profile | F: + RDNA3 switches, core isolation | v0.1.43.1 / v0.1.45 config | G: v0.2.3 fixes + `STRATA_HC_Q8=1` |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Chat decode (median) | 20.0 tok/s | 20.7 | 22.7 | 21.0 | 20.9 (peak 31.2) | 18.4 (peak 28.0) | 18.3 (peak 29.8) | **24.2** (peak **32.3**) |
| Chat time to first token | 2.03 s | 1.93 | 2.13 | 2.03 | 1.86 | 1.81 | **1.62** | 1.82 (1.66–2.06) |
| 4K prompt ingestion | 258.4 tok/s | 265.9 | 264.2 | 268.1 | 268.1 | 265.8 | 277.2 | **302.8** |
| 16K prompt ingestion | 281.8 tok/s | 285.6 | 283.9 | 286.0 | 288.8 | 291.7 | 289.9 | **334.4** |
| 16K time to first token | 57.0 s | 56.3 | 56.6 | 56.2 | 55.7 | 55.1 | 55.4 | **48.1** |
| Agent decode | 22.8 tok/s | 21.5 | 23.8 | **26.1** | 25.9 | 21.3 | 20.2 | **25.9** (peak **31.0**) |
| Agent turn time to first token | 13.3 s | 13.0 | 12.9 | 12.9 | 12.8 | 12.9 | 12.3 | **11.3** |

Numbers are medians over the bench's runs. The active configuration combines Arm E, Arm F and Arm G: `STRATA_ADAPT_OVERLAP=1`,
`STRATA_ADAPT_OVERLAP_RESIDENT=1`, `STRATA_ROUTE_TAIL_SKIP=7`, `STRATA_ROUTE_RESIDENT=0.5`, fusion and RDNA3 switches,
WMMA prompt GEMMs (`STRATA_HIP_WMMA=1`), the gfx1102 SIMT QSA scorer (`STRATA_SELECT_SIMT=1`), Q8_0 hyper-connection weights
(`STRATA_HC_Q8=1`), core isolation (`STRATA_AUX_CPUS=auto`), and a custom expert profile built
from coding traces with `tools/make_profile_mix.py`.

## What it adds to Strata

### 1. Ray, the Assistant
The coding agent is Ray, in the web app's Code tab and in the terminal (the separate Chat tab was removed on
2026-10-23):
- **Who she is:** a casual, direct household assistant and coding agent with a light sense of humour. She never calls
  you "sir" or "madam", and she doesn't assume who is talking: anyone in the house or a guest may be. She uses a name
  only once someone gives it, and she credits the builder only when asked who made her. Her identity note says who
  built what, that she runs on "the home server" (not "this PC", which sounds wrong from a phone), and that the model
  weights come from Alibaba's Qwen team, who neither run her nor see anything she does. Without it, the model credits
  everything to Alibaba.
- **Talk to her:** speech-to-text often mangles her name (Rey, Rae, Wray, Ring); she answers anyway, without
  correcting the spelling, and greetings and small talk get an answer without tool calls. A spoken prompt gets a note
  to answer in plain speech (no tables, code blocks, emoji or URLs, numbers said as words) at full length, and the
  answer is read back in the female Piper HFC voice. A typed prompt gets a normal written answer.
- **Fast spoken answers:** with default automatic thinking (`/effort auto`), greetings, wake words, and household commands answer right away with thinking off, while deep questions and coding turns get appropriate reasoning automatically.
- **Checked with a benchmark:** `tools/ray_persona_bench.py` asks her 22 fixed questions (who is talking, being
  addressed, who made her, persona, spoken answers, and the machine, folder, time and smart home through her tools)
  and scores the answers ([results and method](wiki/artifacts/ray-persona-bench-2026-10-23.md)).

### 2. Unified Shared CLI & Autonomous Coding Agent
The coding agent runs in a persistent background daemon (`tools/dl_sessiond.py`). Both the web app's **Code** tab
and `dl_cli.py --attach` in a terminal are clients of the same session, allowing you to start a task on your phone
and seamlessly inspect or continue it from your terminal:
- Native Markdown formatting, folding reasoning streams, and expandable tool cards.
- **Approvals for destructive actions:** recursive deletes, `sudo`, disk tools, git history rewriting, and writes outside workspace require explicit Approve/Deny.
- **YOLO Mode & Infinite Continuation:** `/yolo` disables approval prompts per session and enables infinite autonomous auto-continuation past `DL_MAX_TURNS` for complex workflows.
- **Stop and Clear respond at once:** Stop closes the model request immediately, also while the engine is still reading a long prompt or the request waits behind another one (measured 1.0 s against a silent test server; before, it waited for the server's next 10 s heartbeat). The Code tab reconnects a live stream that died silently (phone asleep, Wi-Fi or tunnel dropped), so Clear and Stop no longer look stuck until you switch tabs.
- **Plan Mode:** `/plan` investigates read-only and presents an *Execute this plan?* prompt to transition cleanly into act mode.
- **Automatic Thinking Level (`/effort auto`):** default per-turn thinking selector (`tools/dl_effort.py`) that picks `none` for greetings, wake words and smart-home/clock commands, `low` for short factual questions, `medium` for conceptual explanations, and `high` for code, files, errors, plan mode, or follow-up complaints—and escalates mid-turn to `high` if any tool call errors, repeats, or hits a retry guard ([decision](wiki/decisions/auto-thinking-level.md)). Configurable via the Settings/Sampling drawer or `/effort auto|none|low|medium|high` (`/effort default` is auto).
- **Dynamic Reasoning Budget Capping:** tiered token caps (`none: 0`, `low: 1024`, `medium: 2048`, `high: 4096`) passed in `reasoning_budget_tokens` eliminate runaway loops without clipping solutions. On mid-turn escalation, the budget automatically raises to 4,096 tokens alongside effort to `high`.
- **Empirical Response Matrix & CPU Semantic Router:** a 75-item evaluation suite (`tools/bench_effort_matrix.py`) across Voice, Chat, and Coding cohorts and a zero-dependency CPU difficulty router (`tools/dl_effort_scorer.py`, 0.09 ms latency, deterministic CRC32 feature hashing, cosine $k$-NN, safety upward bias).
- **Conversational Continues:** naturally typing *"continue"*, *"keep going"*, or *"go on"* routes directly to turn continuation.

**Keeps its task on long runs** (added 2026-10-20, after a 6-hour run lost its task to context trimming):
- **Trim protection:** when the 64K context is trimmed, your own messages are kept; the CLI's own notes no longer push the task out.
- **The plan is a file:** an approved plan is saved as `PLAN.md` with a `## Progress` checklist that the agent ticks line by line as each check passes. `/planfile <path>` attaches an existing plan. The Code tab shows the progress as a chip (`PLAN 12/34`, red `BLOCKED`).
- **Memory files in the prompt:** `AGENTS.md` (and `CLAUDE.md` where it differs), the wiki's page list and the plan's Progress are part of the system prompt. They are rebuilt only at the start of a request and after a trim, so the engine's prompt cache keeps working.
- **Checks before it may stop:** the done check (in YOLO it sends the agent back until the plan is done or has a `Blocked:` line, and stops after three tries with no change), a browser check (the changed page is loaded in headless Chromium and its console errors go back to the agent), an evidence check ("tests pass" with no test run after the last edit), and one fresh-context review of the diff. Each can be turned off: `DL_DONE_CHECK=0`, `DL_BROWSER_CHECK=0`, `DL_EVIDENCE=0`, `DL_REVIEW=0`.
- **Thinking-loop guard:** a thinking stream that keeps repeating itself is stopped, and the agent is asked for its next action (`DL_LOOP_GUARD=0` turns it off).
- **Undo for every edit** (added 2026-10-20, after a shell-command edit emptied a 33 KB game file): every round that changes files is committed to a git history kept outside the workspace (`~/.local/state/dl-ai/checkpoints/`; `DL_CHECKPOINTS=0` turns it off). A call that empties, deletes or halves a file says so in its result, with the command that restores it (`DL_SHRINK_ALARM=0`). An edit that would copy a trim stand-in (`[N chars removed by D.L. CLI ...]`) into a file is refused. A tool result over 30,000 characters reaches the model as its start and end (`DL_TOOL_RESULT_MAX`), so one long debug print can no longer overflow the context and end a run.
- **Full transcript:** the session daemon writes every event (messages, thinking, tool calls and results, notices) to `~/.local/state/dl-ai/transcripts/<session>/<date>.jsonl` (`DL_TRANSCRIPT=0` turns it off). `/save full` exports the whole run since `/clear`; plain `/save` has only what is still in the context.
- **Checks that see the whole run:** the browser check also finds pages a build script writes, and it runs at every YOLO auto-continue, not only when a request ends. The fresh-context reviewer reads every change since the request started, shell-command edits included (from the checkpoints). Its findings are shown on the Code tab, and its note survives trimming while the agent works through it.
- **Measured** with `tools/dl_agent_bench.py` on a 12-step task with the context squeezed to force 15 trims: before, the task and the plan were trimmed away (2 of 3 checks, 186 tool calls, 56 min); after, 3 of 3 checks with `PLAN.md` kept, 105 tool calls, 50 min. One run each; details in [the wiki](wiki/decisions/dl-cli-task-memory-and-finish-checks.md).

### 3. Local Whisper Speech-to-Text (STT) & Hands-Free Auto-Send
Dictate prompts privately with 100% offline speech recognition:
- **Local Whisper Engine:** runs on the PC host via `whisper.cpp` (`ggml-base.bin`) through `POST /v1/audio/transcriptions` with zero cloud leaks.
- **Real-Time Interim Speech:** progressive interim speech population renders in the composer while walking or talking.
- **Dual-Mode Voice Typing:** click to toggle recording, or hold-to-talk with visual recording pulse.
- **Instant Auto-Send (0ms Delay):** hands-free auto-send populates the text field and submits immediately upon speech pause.
- **Fast spoken responses:** spoken prompts use `/effort auto` by default, answering greetings and home commands instantly while giving complex queries full reasoning room.
- **Mobile Keyboard Suppression:** taps on voice triggers call `navigator.virtualKeyboard.hide()` and set `inputmode="none"`, preventing smartphone on-screen keyboards from obscuring the screen.
- **Browser Speech Fallback:** Web Speech API fallback available when local Whisper is uninstalled.

### 4. Native Browser Text-to-Speech (TTS) & Neural Piper
Listen to responses hands-free without third-party audio streaming:
- **Voice-Gated Auto-Speak:** *"Automatically read new answers aloud"* (on by default) speaks replies only when the input was dictated via STT, preserving silence when typing.
- **20 US Neural Piper Voices:** high-quality local Piper speech synthesis integrated via Linux Speech Dispatcher and Web Speech API. Ray's voice, `en_US-hfc_female-medium`, is the default in the browser and on the desktop; any other voice can be picked in Settings. Where Piper is missing (a phone, Edge, macOS), *Auto* still picks a female voice: Edge's Ava, Chrome's Google US English, Android's local US English voice.
- **Natural Speech Cleaner (`cleanForSpeech`):** strips markdown, emojis, code blocks, box borders, and converts math, units, and symbols to natural spoken words.
- **Mobile Keep-Alive & Controls:** Android Screen WakeLock and MediaSession notification drawer controls (play, pause, stop).

### 5. Home Assistant Smart Home MCP Server
A built-in Model Context Protocol (MCP) server (`tools/homeassistant_mcp.py`) exposes your smart home to the coding agent (the Code tab and the terminal CLI). It runs here with lights on Tuya smart plugs, a Gree air conditioner, a Bambu Lab A1 3D printer and two Xiaomi cameras:
- Direct entity control: lights, switches, media players, climate units (Gree AC), covers, and smart plugs.
- Rooms: entities carry their Home Assistant area, so "turn off the living room lights" finds every light there, plug-powered ones included.
- Live camera snapshots: captures and saves camera feeds to the workspace for multimodal inspection.
- Jinja2 template rendering and entity state history lookups.
- Interactive MCP tools explorer in the web GUI via `/mcp`.
- Loads when it is needed, not by default: when your message mentions the smart home, or when the agent turns it on itself.

### 6. Tools & On-Demand Knowledge Suites (38 MCP Servers)

Ray features a zero-overhead, on-demand MCP router (`tools/dl_mcp.py`) that keeps tools dormant to save prompt context until matched by request triggers or explicitly toggled via `/mcp on <name>`. Each server answers `ping`, sends nothing back to notifications, and marks a failed call with `isError`, so the automatic thinking level sees tool failures:

| Suite / Category | Servers & Tools | What It Covers |
| :--- | :--- | :--- |
| **Self-Identity & Project** | `ray_identity` | Who Ray (Rei) is, plus this PC's hardware, the running engine's address, model and settings, the services and the git status, all read when she is asked (nothing hardcoded that can go stale), and the active MCP catalog. |
| **Reasoning Escalation** | `deepseek` (`deepseek_reason`) | DeepSeek cloud reasoning for heavy mathematics and frontier logic. Every call shows an approval card with the full prompt that would leave the PC; `/mcp trust deepseek` stops asking for the session, `/mcp ask deepseek` asks again. The key comes only from `DEEPSEEK_API_KEY` in `~/.config/dl-ai/secrets.env`. |
| **Smart Home & Automation** | `homeassistant` (Bambu, Xiaomi, plugs, lights, AC), `schedule` | Smart home control, camera snapshots, scheduled jobs, recurring reminders. |
| **Web & Productivity** | `exa`, `fetch`, `playwright`, `deepl`, `proton`, `gmail`, `drive`, `docs` | Web search, headless browser automation, translation, email, and Google Workspace. |
| **Development & Standards** | `context7`, `modernweb`, `rfc`, `osv`, `devstandards` | Live library documentation, Modern Web Guidance (CSS/HTML5), IETF RFC protocol specs, OSV package vulnerabilities (CVEs), Game Programming Patterns, MDN. |
| **Science & Biomedical** | `arxiv`, `openalex`, `europepmc`, `pubchem`, `clinicaltrials`, `opentargets`, `reactome` | arXiv preprints (AI/CS/Math), OpenAlex 250M+ scholarly works graph, Europe PMC open access papers, PubChem chemical formulas, ClinicalTrials.gov studies, Open Targets drug targets, Reactome biological pathways. |
| **Hardware, 3D & Laws** | `solidcraft`, `print3d`, `cadmaterials`, `osm`, `laws`, `weather`, `minipaint`, `electronics`, `networking` | SolidCraft parametric 3D CAD modeling & engine control (parametric enclosures, brackets, flanges, standoffs, custom sketches/extrusions/cuts, automatic `.solidcraft`/`.step`/`.stl`/`.3mf` export and GPU-rendered PNG snapshots saved directly into Ray's workspace, live GUI control via port 7878), Klipper G-code & Bambu/Prusa filament presets, STEP AP242/IGES & AFLOW material properties, OpenStreetMap geocoding, Croatian (Zakon.hr/NN) & EU (EUR-Lex/CURIA) laws, Open-Meteo live weather, miniature painting & wargaming (3,340+ paint conversions across Citadel, Vallejo, AK, Army Painter, airbrush thinning, NMM/slapchop, Warhammer 40k / Kill Team wound matrix, AP saves, FNP, faction color schemes & BGG mechanics), electronics & components (IPC-2152 PCB trace width & current capacity, copper weight, thermal rise, ESP32/RP2040 decoupling capacitor rules, LCSC/JLCPCB parts, SMD resistor code decoder), networking & LAN (SFP/SFP+/QSFP optics, OM3/OM4/OS2 fiber standards, RJ45 T568A/B cabling, PoE, IEEE MAC vendor lookup). |
| **Photo, Video, Audio & Drones** | `photovideo`, `drones` | Exposure & 180° cinematic shutter calculations, camera log profiles (Sony S-Log3, Canon C-Log3, DJI D-Log, Panasonic V-Log), DaVinci Resolve Color Space Transform (CST) node tree workflow (DWG / DaVinci Wide Gamut intermediate, Rec.709 delivery, QuickTime gamma tags, shortcuts), storyboard shot composition (ELS, LS, MCU, CU, OTS, Dutch angles), audio engineering loudness targets (YouTube/Spotify -14 LUFS, Broadcast EBU R128 -23 LUFS, Podcasts -16 LUFS, True Peak), mic polar patterns (shotgun, lavalier, cardioid), 32-bit float audio, DJI drone hardware specifications (Mini 4 Pro, Air 3, Mavic 3 Pro), CCAA & EASA Croatian drone laws, and Croatia Control AMC Portal automated airspace booking (Zagreb LDZA CTR). |
| **Zagreb & Croatia Live** | `zagreb`, `croatia_live` | ZET tram lines (ends from ZET's own GTFS feed; day 1-17, night 31-34) & live disruption alerts (zet.skoljka.org), BAJS (Nextbike) live bike availability across all 200 stations in Zagreb, on-duty pharmacies (the City of Zagreb's list, with its date), specialized emergencies (Poison Control CKO, pediatric ER Klaićeva/Rebro, vet clinic VetFak, dental emergency), where to look up Čistoća's waste schedule for an address, real-time Zagreb air quality (European AQI, PM2.5, PM10), HAK live highway/border conditions (A1/A3, Lučko, Bregana, Macelj, Bajakovo), official DHMZ meteorological observations, HNB official exchange rates (EUR/USD/BAM/CHF/GBP), state holidays & non-working Sunday shopping rules (Zakon o trgovini), current fuel prices (median over every station in the Ministry of Economy's price register, read live), and Zagreb LDZA aviation METAR. |

### 7. Workspace, JIT Model Loading & Remote Access
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
  - **Code:** Ray, the shared coding agent, with voice typing, read-aloud TTS, and workspace files (*Attach* adds an
    `@path` reference to the prompt).
  - **Monitor:** real-time GPU, VRAM, RAM, and KV cache monitoring.
- **Terminal:** run `python3 tools/dl_cli.py --attach` to join the shared session, and `/detach` to leave it
  running.
- **Commands** (in either client):

  | Command | What it does |
  | :--- | :--- |
  | `/plan`, `/act` | switch between plan mode and act mode |
  | `/yolo` | turn approvals off and enable infinite continuation |
  | `/continue` | continue execution of multi-turn assistant plans |
  | `/planfile <path>\|off` | attach a plan file the agent works from and ticks (`PLAN.md`) |
  | `/effort none\|low\|medium\|high\|auto` | this session's reasoning effort (`auto`, the default, picks per turn and escalates on tool failures; `/effort default` is auto) |
  | `/cd <path>` | change the project folder |
  | `/status`, `/health` | engine status, hardware health |
  | `/mcp`, `/mcp on\|off <server>` | list the MCP servers, turn one on or off |
  | `/mcp trust\|ask <server>` | stop or resume a server's approval card for this session (e.g. DeepSeek) |
  | `/speak` | read the latest assistant message aloud |
  | `/exa <query>`, `/context7 <library>` | web search, library docs |
  | `/diff`, `/secrets`, `/test`, `/wiki` | review the diff, scan for secrets, run tests, search the wiki |
  | `/save` | save the chat as Markdown |
  | `/clear` | reset the conversation |
  | `!<command>` | run a shell command |

- **API:** the server speaks the OpenAI and Anthropic APIs on `/v1` (`/v1/chat/completions`, `/v1/audio/transcriptions`). Send the key as `Authorization: Bearer`.

## Security

- **No secrets in the repository.** Keys live in `~/.config/dl-ai/secrets.env`, and the pre-commit hook blocks a
  commit that contains one. It also blocks added lines that carry this machine's home path, the folder the checkout
  sits in, or the profile's email address; it reads those at run time, so the hook names none of them.
- **Cloud calls ask first.** DeepSeek is the only tool that sends your text off the PC, and it asks on a card before
  every call unless you typed `/mcp trust deepseek` for the session.
- **Browser requests** need a valid Cloudflare Access token (signature, issuer, audience and expiry are checked)
  or the API key. Keys are never accepted in URLs.
- **The session daemon** listens only on a Unix socket in your runtime directory (mode 600).
- **Workspace file access** is confined to the workspace directory.

## Credits and license

Strata, the engine, the server and the installer, is by
[Niko1221 and the Strata contributors](https://github.com/Niko1221/Strata), under the MIT license. The model weights
are Qwen3.8-Flash-Next from Alibaba's Qwen team. Ray, D.L. CLI and the rest of this fork are by
[Damir](https://github.com/DamirLukina88). This fork keeps
that license ([LICENSE](LICENSE)). Upstream's own documentation is in [docs/](docs/), and its paper is in
[docs/paper](docs/paper).
