# Ray: what this fork adds

Everything Ray and this fork add to Strata, in detail: the panda, the assistant, the shared coding agent, voice, the smart home, the MCP tools and remote access.

[← Back to the README](../README.md)

## Meet Ray

Ray is a little red panda drawn in dots. In the web app's Code tab he sits on the top-left edge of the input box, and
he is there only while he has something to do. All the pictures below come from the web app's own drawing code
(`serve/web/rayface.js`), rendered by `tools/make_ray_media.py`. That includes his motion while talking, which follows
real speech in his Piper voice.

<table>
<tr>
<td align="center"><img src="media/ray/thinking.gif" alt="Ray thinking, paw on his chin, question marks rising" width="220"><br><b>Thinking</b></td>
<td align="center"><img src="media/ray/talking.gif" alt="Ray reading a reply aloud" width="220"><br><b>Talking</b></td>
<td align="center"><img src="media/ray/goodbye.gif" alt="Ray's warm goodbye and fade" width="220"><br><b>Goodbye</b></td>
</tr>
<tr>
<td>While the model works on your prompt, his paw goes to his chin, his eyes go up and to the side, and question
marks rise. For a typed prompt he leaves as soon as the answer starts.</td>
<td>While he reads a reply aloud, he moves with the loudness of his voice, read 50 ms before it is heard. He squashes
and stretches on syllables, nods on stressed ones, blinks when a thought ends, and his ears and tail follow a beat later.</td>
<td>When he has finished speaking, he gives a happy squint and a small nod, then fades out slowly.</td>
</tr>
</table>

**His moods.** Simple rules on each sentence pick a mood, used at 60% strength and held for at least 2 s, so he never
flickers. A sentence about an error or an apology makes him concerned, one ending in `?` makes him curious, "maybe"
or "hmm" makes him thoughtful, and so on.

<p align="center"><img src="media/ray/moods.png" alt="Ray's eight moods: neutral, happy, excited, surprised, curious, thinking, concerned, goodbye" width="760"></p>

**Cocoa breaks.** Now and then, while the model works, Ray takes a break with a mug of hot chocolate. Once a
think has gone on for 8 s there is a 1 in 3 chance, and it never happens on two thinks in a row. The mug pops up
beside him on the input box, steaming. He picks it up, holds it in both paws and sips with his eyes closed, then
puts it back. Each break picks one of four styles at random, never the same one twice running. If he starts
speaking or the answer arrives, the mug goes away at once.

<table>
<tr>
<td align="center"><img src="media/ray/cocoa-classic.gif" alt="Ray's classic cocoa sip" width="200"><br><b>Classic sip</b></td>
<td align="center"><img src="media/ray/cocoa-savour.gif" alt="Ray savouring his cocoa" width="200"><br><b>Slow savour</b></td>
<td align="center"><img src="media/ray/cocoa-hot.gif" alt="Ray finding his cocoa too hot" width="200"><br><b>Too hot!</b></td>
<td align="center"><img src="media/ray/cocoa-thinking.gif" alt="Ray sipping cocoa while he thinks" width="200"><br><b>Sips while thinking</b></td>
</tr>
<tr>
<td>One long sip, an "ahh" with an ear wiggle and a short cosy hold.</td>
<td>He cradles the mug under his chin, breathes in the steam and sways gently. Two slow sips with a happy sigh between them.</td>
<td>He blows on it and takes a careful test sip, then jolts: eyes wide, ears up, the mug pulled away. He blows again, then takes the real sip.</td>
<td>He keeps thinking with the mug in both paws, eyes up and question marks rising, and sips now and then.</td>
</tr>
</table>

**At work on long tasks.** When a turn runs long (30 s, or 6 tool calls), Ray works at something that fits the task.
The Code tab tells him the prompt and every tool call, so he knows the kind of work: code, a CAD model, a 3D print or
maths. Three failed tool calls in a turn make it a hard problem. A round is about 35 s, followed by 20 s of plain
thinking, then a new pick at random. The usual activity for each kind of work comes up most often, and none plays
three rounds running. The newest kind of work counts, so a turn that models a part and then prints it moves from
blueprints to measuring between rounds. He only ever holds one prop.

<table>
<tr>
<td align="center"><img src="media/ray/work-blueprint.gif" alt="Ray drawing a blueprint" width="200"><br><b>Drawing a blueprint</b></td>
<td align="center"><img src="media/ray/work-measure.gif" alt="Ray measuring a 3D print with calipers" width="200"><br><b>Measuring a print</b></td>
<td align="center"><img src="media/ray/work-cube.gif" alt="Ray solving a Rubik's cube" width="200"><br><b>Solving a Rubik's cube</b></td>
<td align="center"><img src="media/ray/work-maths.gif" alt="Ray working out an equation" width="200"><br><b>Working out equations</b></td>
</tr>
<tr>
<td>A blue sheet on his lap. He draws a box with a dimension line dot by dot, nods, wipes the sheet, then draws a gear.</td>
<td>Calipers on a 3D-printed cube. He squints and reads 20.0, measures again, gets 19.9, and a question mark pops up.</td>
<td>He turns rows and columns until the front is all blue, then hops with the cube held up, and it sparkles.</td>
<td>He writes 2x+1 = 7 and taps the pencil on his chin. A light bulb comes on, and on a fresh page he writes x=3 and underlines it.</td>
</tr>
</table>

| Kind of work | What he does (how often) |
| :-- | :-- |
| Code | blueprint 3, equations 1, Rubik's cube 1 |
| CAD and 3D models | blueprint 3, measuring 1 |
| 3D printing | measuring 3, blueprint 1 |
| Maths | equations 3, Rubik's cube 1 |
| A hard problem (3 failed tool calls) | Rubik's cube 3, plus the usual one for the work 1 |
| A long think with no kind of work recognised | a Rubik's cube in 1 round of 3 |

**At the control panel.** When Ray calls Home Assistant, about 1 time in 2 (once a turn), he works a little control
panel straight away: one round of 6 to 8 s, turning knobs and pressing buttons. The panel follows the action: lights
and switches get the lamp, scenes or several devices at once get the mixing desk, and anything else gets either one. It takes over
from a cocoa break or a long-task round, and it goes as soon as the answer starts.

<table>
<tr>
<td align="center"><img src="media/ray/home-lamp.gif" alt="Ray turning on a lamp at a control panel" width="200"><br><b>Desk panel and lamp</b></td>
<td align="center"><img src="media/ray/home-mixer.gif" alt="Ray working a mixing desk that lights a house's windows" width="200"><br><b>Mixing desk</b></td>
</tr>
<tr>
<td>He turns a knob and presses a button, and the lamp comes on. He dims it and brings it back up, then switches it from warm to cool white.</td>
<td>With both paws he pushes up faders and turns a knob. Each one lights a window of a little house above him, then he bobs his head to the meter.</td>
</tr>
</table>

With *reduced motion* set in the system, he takes no cocoa breaks and plays none of these animations. To see them
without waiting, run `RayFace.cocoa("classic" | "savour" | "hot" | "thinking")` or
`RayFace.work("blueprint" | "measure" | "cube" | "maths" | "lamp" | "mixer")` in the browser
console while he is thinking.

He has no talking mouth on purpose. Every mouth that copied the speech looked uncanny, so he speaks through motion,
and his mouth opens only on the strongest syllables. His voice is pitched up to 1.5 by default, a little cartoon-like
to suit him. On light themes, his dot-matrix border is rendered with a bold dark outline so his white cheeks and ears stay crisp and clear. Click him to stop him talking. Two switches in About turn him off: *Show Ray while speaking* and
*Show Ray thinking on every prompt*. The same panda is the app icon and the browser tab icon.

## What it adds to Strata

### 1. Ray, the Assistant
The coding agent is Ray, in the web app's Code tab and in the terminal (the separate Chat tab was removed on
2026-10-23):
- **Who he is:** the household's little red panda, AI assistant and coding agent: casual and direct, with a light sense of humour. He never calls
  you "sir" or "madam", and he doesn't assume who is talking: anyone in the house or a guest may be. He uses a name
  only once someone gives it, and he credits the builder only when asked who made him. His identity note says who
  built what, that he runs on "the home server" (not "this PC", which sounds wrong from a phone), and that the model
  weights come from Alibaba's Qwen team, who neither run him nor see anything he does. Without it, the model credits
  everything to Alibaba.
- **Talk to him:** speech-to-text often mangles his name (Rey, Rae, Wray, Ring); he answers anyway, without
  correcting the spelling, and greetings and small talk get an answer without tool calls. A spoken prompt gets a note
  to answer in plain speech (no tables, code blocks, emoji or URLs, numbers said as words) at full length, and the
  answer is read back in the male Piper HFC voice. A typed prompt gets a normal written answer.
- **He speaks while he writes:** a spoken prompt's answer is read sentence by sentence as the model writes it
  (`serve/web/speakstream.js`), not after the whole turn. When he thinks before answering and then uses a tool, he
  first says in one short sentence what he is about to do ("Let me check the live weather for Zagreb."), so you hear
  him while the tool runs. Measured on three spoken prompts on this PC: his first word came 3 to 67 s sooner (for
  example 15 s instead of 82 s); most of the rest of the wait is the model thinking. Canned filler lines, a soft
  "thinking" sound and Piper "hmm" sounds were tried and dropped as unnatural. About > *Speak while Ray writes*
  turns it off ([details](../wiki/decisions/desktop-piper-voice-switching-and-stt-auto-speak.md)).
- **Fast spoken answers:** with default automatic thinking (`/effort auto`), greetings, wake words, and household commands answer right away with thinking off, while deep questions and coding turns get appropriate reasoning automatically.
- **Checked with a benchmark:** `tools/ray_persona_bench.py` asks him 22 fixed questions (who is talking, being
  addressed, who made him, persona, spoken answers, and the machine, folder, time and smart home through his tools)
  and scores the answers ([results and method](../wiki/artifacts/ray-persona-bench-2026-10-23.md)).

### 2. Unified Shared CLI & Autonomous Coding Agent
The coding agent runs in a persistent background daemon (`tools/dl_sessiond.py`). Both the web app's **Code** tab
and `dl_cli.py --attach` in a terminal are clients of the same session, allowing you to start a task on your phone
and seamlessly inspect or continue it from your terminal:
- Native Markdown formatting, folding reasoning streams, and expandable tool cards.
- **Approvals for destructive actions:** recursive deletes, `sudo`, disk tools, git history rewriting, and writes outside workspace require explicit Approve/Deny.
- **YOLO Mode & Infinite Continuation:** `/yolo` disables approval prompts per session and enables infinite autonomous auto-continuation past `DL_MAX_TURNS` for complex workflows.
- **Saved conversations:** `/clear` and the **New** button save the conversation they end, so nothing is lost.
  - `/sessions [words]` lists the saved ones, newest first, and searches their titles and messages. `/resume N` brings one back after saving the current one. `/rename` and `/delete N` change the list; deleted ones go to a `.deleted` folder.
  - In the Code tab, the **Sessions** drawer does the same.
  - They are kept in `~/.local/state/dl-ai/archive/<session>/` and shared by the web app and the terminal ([decision](../wiki/decisions/saved-cli-sessions.md)).
- **Edit, rewind and branch:** every past prompt in the Code tab has ✎ Edit, ↶ Rewind and ⑂ Branch buttons; in the terminal, `/prompts` numbers the prompts.
  - `/edit N <text>` replaces prompt N and runs the new text.
  - `/rewind N` goes back to just before prompt N (it and what followed are removed).
  - `/branch N [text]` keeps the whole conversation in Sessions and goes on from before prompt N.
  - A prompt that a session handoff or context reset already archived cannot be gone back to; the command says so and changes nothing.
- **Queued messages while Ray works:** if you send a prompt or command while Ray is busy, it is queued instead of lost. Ray picks up queued prompts at the next step (right after the current tool round finishes, before the finish checks, or when the turn ends), keeping the prompt cache and rewind marks intact. The Code tab shows a queued bar above the input box with **Send now** (interrupts the current step and runs it at once), **✎** Edit (moves it back to the input box) and **✕** Remove; `/queue` lists or clears them from either client ([decision](../wiki/decisions/shared-cli-session-daemon.md)).
- **The feed lets you read:** while an answer streams, scrolling up (wheel, finger or PageUp) stops the feed from following, and scrolling back to the bottom resumes it. A message you send always scrolls into view.
- **Stop and Clear respond at once:** Stop closes the model request immediately, also while the engine is still reading a long prompt or the request waits behind another one (measured 1.0 s against a silent test server; before, it waited for the server's next 10 s heartbeat). The Code tab reconnects a live stream that died silently (phone asleep, Wi-Fi or tunnel dropped), so Clear and Stop no longer look stuck until you switch tabs.
- **Plan Mode:** `/plan` investigates read-only and presents an *Execute this plan?* prompt to transition cleanly into act mode.
- **Automatic Thinking Level (`/effort auto`):** default per-turn thinking selector (`tools/dl_effort.py`) that picks `none` for greetings, wake words and smart-home/clock commands, `low` for short factual questions, `medium` for conceptual explanations, and `high` for code, files, errors, plan mode, or follow-up complaints—and escalates mid-turn to `high` if any tool call errors, repeats, or hits a retry guard ([decision](../wiki/decisions/auto-thinking-level.md)). Configurable via the Settings/Sampling drawer or `/effort auto|none|low|medium|high` (`/effort default` is auto).
- **Dynamic Reasoning Budget Capping:** tiered token caps (`none: 0`, `low: 1024`, `medium: 2048`, `high: 4096`) passed in `reasoning_budget_tokens` eliminate runaway loops without clipping solutions. On mid-turn escalation, the budget automatically raises to 4,096 tokens alongside effort to `high`.
- **Empirical Response Matrix & CPU Semantic Router:** a 75-item evaluation suite (`tools/bench_effort_matrix.py`) across Voice, Chat, and Coding cohorts and a zero-dependency CPU difficulty router (`tools/dl_effort_scorer.py`, 0.09 ms latency, deterministic CRC32 feature hashing, cosine $k$-NN, safety upward bias).
- **Conversational Continues:** naturally typing *"continue"*, *"keep going"*, or *"go on"* routes directly to turn continuation.

**Keeps its task on long runs with Two-Tier Wiki Handoff** (updated 2026-11-01; replaces mechanical context trimming):
- **Two-Tier Wiki Handoff (`DL_HANDOFF=1`):** when the ~50k prompt token limit is reached in the 64K context window (or on `/handoff`), D.L. CLI automatically generates a dense 4-section Active Handoff Brief with ~100% KV cache hit rate and saves it to `wiki/handoffs/latest.md` alongside an archived stretch log in `wiki/handoffs/handoff-<timestamp>-part<N>.md`.
- **Clean Session Reload:** the conversation resets in place to a lean ~4k token clean state containing the system prompt, protected user instructions, the handoff brief, and recent file anchors. This avoids the 45–55 s prefill latency penalty of mechanical middle trimming, dropping prefill to ~1.5 s while preserving complete task continuity and next actions ([decision](../wiki/decisions/wiki-handoff-and-oom-fixes.md)).
- **Mid-Stream Crash Detection & Auto-Retry:** catches unexpected engine failures mid-turn, automatically waits for model reload, and retries up to 2 times without interrupting user tasks.
- **Elastic Vision & Memory Protection:** vision weights stay unloaded when not actively inspecting pictures (`elastic: true`, 1.15 GiB RAM saved), and systemd `OOMPolicy=continue` guarantees service stability under memory pressure.
- **The plan is a file:** an approved plan is saved as `PLAN.md` with a `## Progress` checklist that the agent ticks line by line as each check passes. `/planfile <path>` attaches an existing plan. The Code tab shows the progress as a chip (`PLAN 12/34`, red `BLOCKED`).
- **Memory files in the prompt:** `AGENTS.md` (and `CLAUDE.md` where it differs), the wiki's page list and the plan's Progress are part of the system prompt. They are rebuilt only at the start of a request and after a handoff, keeping the prompt cache hot.
- **Checks before it may stop:** the done check (in YOLO it sends the agent back until the plan is done or has a `Blocked:` line, and stops after three tries with no change), a browser check (the changed page is loaded in headless Chromium and its console errors go back to the agent), an evidence check ("tests pass" with no test run after the last edit), and one fresh-context review of the diff. Each can be turned off: `DL_DONE_CHECK=0`, `DL_BROWSER_CHECK=0`, `DL_EVIDENCE=0`, `DL_REVIEW=0`.
- **Thinking-loop guard:** a thinking stream that keeps repeating itself is stopped, and the agent is asked for its next action (`DL_LOOP_GUARD=0` turns it off).
- **Undo for every edit:** every round that changes files is committed to a git history kept outside the workspace (`~/.local/state/dl-ai/checkpoints/`; `DL_CHECKPOINTS=0` turns it off). A call that empties, deletes or halves a file says so in its result, with the command that restores it (`DL_SHRINK_ALARM=0`). A tool result over 30,000 characters reaches the model as its start and end (`DL_TOOL_RESULT_MAX`), preventing context overflows.
- **Full transcript:** the session daemon writes every event to `~/.local/state/dl-ai/transcripts/<session>/<date>.jsonl` (`DL_TRANSCRIPT=0` turns it off). `/save full` exports the whole run since `/clear`; plain `/save` has only what is still in the context.
- **Checks that see the whole run:** the browser check also finds pages a build script writes, and it runs at every YOLO auto-continue, not only when a request ends. The fresh-context reviewer reads every change since the request started, shell-command edits included (from the checkpoints). Its findings are shown on the Code tab, and its note survives handoffs while the agent works through it.

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
- **Persistent Speaker Mode Toggle:** clicking the header speaker icon in the Code tab arms persistent speak mode (`strata.tts_speak_toggle`). When enabled, typed prompts are also answered aloud in Ray's spoken persona (with tool preambles and streaming speech), allowing you to type and listen hands-free. Stopping mid-reply silences only that turn.
- **20 US Neural Piper Voices:** high-quality local Piper speech synthesis integrated via Linux Speech Dispatcher and Web Speech API. Ray's voice, `en_US-hfc_male-medium` (male since 2026-10-28), is the default on the server, in the browser and on the desktop; any other voice can be picked in Settings. Where the server voice is off and Piper is missing (Edge, macOS), *Auto* picks a male voice by name (Edge's Andrew or Guy, Chrome's Google UK English Male); Android names voices by language only, so there it is the local US English voice.
- **Ray's voice from the server:** `POST /v1/audio/speech` (OpenAI-style `input`, `voice`, `speed`; WAV, `serve/speech.py`) runs Piper on the home server, so phones hear the same voice as the PC (measured 0.39 s for 3.4 s of speech). The web app uses it by default (About: *Use Ray's voice from the server*) and falls back to the browser voice if it fails.
- **Ray's avatar:** a little red panda sitting on the input box who thinks while the model works and moves with his voice while he reads a reply aloud ([Meet Ray](#meet-ray)). He features a bold, dark outline on light themes for crisp contrast. Now and then he takes a cocoa break, and on long tasks he works at something that fits: a blueprint, calipers on a 3D print, a Rubik's cube or equations. When he calls Home Assistant, he sometimes works a little control panel: a lamp or a mixing desk. Click him to stop the speech. Turn him off in About.
- **Speed and pitch:** the sliders in About work for the server voice and the browser voice. Piper has no pitch setting, so pitch is made by playing the speech faster, which was asked from the server that much slower, so the pace stays at the Speed setting. The default pitch is 1.5.
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
- In the Code tab, a call sometimes shows Ray at a control panel: turning on a lamp for lights and switches, or a mixing desk for scenes and several devices ([At the control panel](#meet-ray)).

### 6. Tools and MCP Servers (38 servers)

**Always there.** Ray's own tools are in every request:
- `run_command`, `view_file`, `write_to_file` and `replace_file_content` work on files and the shell in the workspace.
- `switch_workspace` changes the folder he works in.
- `local_wiki` reads and saves the project's `wiki/`.
- `get_system_health` and `get_engine_status` report the PC and the engine.
- `save_chat` and `clear_conversation` manage the conversation.
- `mcp` turns the servers below on and off.

Plan mode (`/plan`) gets the read-only ones.

**Slightly broken calls still count.** The server reads a tool call the model wrote with a small slip as the call it
meant (ported from upstream Strata 0.2.8): a JSON argument with a trailing comma, single quotes or an unclosed bracket,
a missing `</function>` (also inside the thinking), a stray `</think>` before the call, and a tool call quoted inside a
text argument kept exactly. What was repaired is counted in `/metrics/prometheus` (`strata:tool_args_repaired_total`);
the details are in [DETAILS](DETAILS.md).

**On demand.** Every tool description is sent again with every turn, and the local model pays for it in prompt time.
So the 38 MCP servers in `~/.config/dl-ai/mcp.json` stay off until a request needs them (`tools/dl_mcp.py`):
- **They turn on by themselves:** a server starts when your message matches its trigger words (English, Croatian and
  German), or when Ray turns it on with his `mcp` tool. One whose tools go unused for 3 turns is turned off again.
- **A cap on tools at once:** 25 by default (`max_tools`; 45 on this PC); past it, the server used longest ago goes
  first.
- **By hand:** `/mcp` lists them all, with `/mcp on NAME` and `/mcp off NAME` to switch one. The Code tab shows the
  ones that are on as chips.
- **Approvals:** tools that send or share something (email, Drive sharing, a cloud call) show an approval card first.
  `/mcp trust NAME` stops the card for the session, and `/mcp ask NAME` brings it back.
- **Keys stay narrow:** each server gets only the keys it names from `~/.config/dl-ai/secrets.env`, never the whole
  file.
- **Errors reach the thinking level:** every server answers `ping`, and a failed call is marked `isError`, so the
  automatic thinking level sees tool failures.
- **Four are part of Ray himself, with no separate program:** `exa`, `deepl`, `proton` and `schedule`.

| Group | Servers | What they cover |
| :--- | :--- | :--- |
| **Ray himself** | `ray_identity` | Who Ray is, plus this PC's hardware, the running engine's address, model and settings, the services and the git status. All of it is read when he is asked, so nothing hardcoded can go stale. Also the MCP catalogue. |
| **Smart home and jobs** | `homeassistant`, `schedule` | Lights, plugs, the Gree air conditioner, Bambu Lab A1 printer, Xiaomi cameras and air purifier, Zigbee sensors ([section 5](#5-home-assistant-smart-home-mcp-server)). Jobs: a prompt or one exact action at a set time or on repeat (reminders, daily summaries). |
| **Cloud reasoning** | `deepseek` | DeepSeek for heavy maths and long proofs. Every call shows an approval card with the full prompt that would leave the PC. The key comes only from `DEEPSEEK_API_KEY`. |
| **Web, mail and documents** | `exa`, `fetch`, `playwright`, `deepl`, `proton`, `gmail`, `drive`, `docs` | Exa web search, reading a page as Markdown, and a real headless browser that can click and fill forms. DeepL translation of texts, HTML emails and workspace files. Proton Mail through Bridge, Gmail, Google Drive and Google Docs: search, read, draft, and send or share after approval. |
| **Programming** | `context7`, `modernweb`, `rfc`, `osv`, `devstandards` | Up-to-date library docs (Context7), modern HTML and CSS guidance, IETF RFCs, known vulnerabilities in PyPI, npm, Go and crates.io packages (OSV), game programming patterns and MDN. |
| **Knowledge and science** | `wikipedia`, `arxiv`, `openalex`, `europepmc`, `pubchem`, `clinicaltrials`, `opentargets`, `reactome` | Wikipedia overviews, arXiv preprints, OpenAlex (250M+ scholarly works), Europe PMC open-access papers, PubChem chemistry, ClinicalTrials.gov studies, Open Targets drug targets, Reactome pathways. |
| **Making things** | `solidcraft`, `print3d`, `cadmaterials`, `electronics`, `networking`, `minipaint` | SolidCraft parametric 3D CAD modeling & engine control (parametric enclosures, brackets, flanges, standoffs, custom sketches/extrusions/cuts, automatic `.solidcraft`/`.step`/`.stl`/`.3mf` export and GPU-rendered PNG snapshots saved directly into Ray's workspace, live GUI control via port 7878), Klipper G-code & Bambu/Prusa filament presets, STEP AP242/IGES & AFLOW material properties, miniature painting & wargaming (3,340+ paint conversions across Citadel, Vallejo, AK, Army Painter, airbrush thinning, NMM/slapchop, Warhammer 40k / Kill Team wound matrix, AP saves, FNP, faction color schemes & BGG mechanics), electronics & components (IPC-2152 PCB trace width & current capacity, copper weight, thermal rise, ESP32/RP2040 decoupling capacitor rules, LCSC/JLCPCB parts, SMD resistor code decoder), networking & LAN (SFP/SFP+/QSFP optics, OM3/OM4/OS2 fiber standards, RJ45 T568A/B cabling, PoE, IEEE MAC vendor lookup). |
| **Photo, video, audio and drones** | `photovideo`, `drones` | Exposure & 180° cinematic shutter calculations, camera log profiles (Sony S-Log3, Canon C-Log3, DJI D-Log, Panasonic V-Log), DaVinci Resolve Color Space Transform (CST) node tree workflow (DWG / DaVinci Wide Gamut intermediate, Rec.709 delivery, QuickTime gamma tags, shortcuts), storyboard shot composition (ELS, LS, MCU, CU, OTS, Dutch angles), audio engineering loudness targets (YouTube/Spotify -14 LUFS, Broadcast EBU R128 -23 LUFS, Podcasts -16 LUFS, True Peak), mic polar patterns (shotgun, lavalier, cardioid), 32-bit float audio, DJI drone hardware specifications (Mini 4 Pro, Air 3, Mavic 3 Pro), CCAA & EASA Croatian drone laws, and Croatia Control AMC Portal automated airspace booking (Zagreb LDZA CTR). |
| **Places, laws and live data** | `osm`, `weather`, `laws`, `zagreb`, `croatia_live` | OpenStreetMap geocoding, Open-Meteo live weather for any city, Croatian (Zakon.hr, Narodne novine) and EU (EUR-Lex, CURIA) laws. Zagreb and Croatia: ZET tram lines (ends from ZET's own GTFS feed; day 1-17, night 31-34) & live disruption alerts (zet.skoljka.org), BAJS (Nextbike) live bike availability across all 200 stations in Zagreb, on-duty pharmacies (the City of Zagreb's list, with its date), specialized emergencies (Poison Control CKO, pediatric ER Klaićeva/Rebro, vet clinic VetFak, dental emergency), where to look up Čistoća's waste schedule for an address, real-time Zagreb air quality (European AQI, PM2.5, PM10), HAK live highway/border conditions (A1/A3, Lučko, Bregana, Macelj, Bajakovo), official DHMZ meteorological observations, HNB official exchange rates (EUR/USD/BAM/CHF/GBP), state holidays & non-working Sunday shopping rules (Zakon o trgovini), current fuel prices (median over every station in the Ministry of Economy's price register, read live), and Zagreb LDZA aviation METAR. |

Separate from Ray, Strata has its own MCP server for installing and running the engine from another AI app
([docs/MCP_SERVER.md](MCP_SERVER.md)).

### 7. Workspace, JIT Model Loading & Remote Access
- **Server File Workspace:** upload files by drag and drop, browse folder trees, stream and resume large downloads.
- **JIT Model Loading & Memory Hygiene:** models load on demand and unload after 8 hours idle. `STRATA_DROP_CACHE_ON_EXIT=1` returns Linux page cache (20+ GB) immediately on exit.
- **Zero-Port Remote Access:** Cloudflare Tunnel over QUIC publishes the app, authenticated via Cloudflare Access JWT.

