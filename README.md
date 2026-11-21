<p align="center"><img src="docs/media/ray/ray.png" alt="Ray, a little red panda drawn in dots, sitting" width="200"></p>

<h1 align="center">Ray</h1>

<p align="center"><b>A private AI assistant and coding agent that runs on one desktop PC, with no cloud model.</b><br>
Built on <a href="https://github.com/Niko1221/Strata">Strata</a> by <a href="https://github.com/DamirLukina88">Damir</a>.</p>

Ray is the household's little red panda. You type or talk to him in a web app or on your phone, and he answers out
loud, writes and runs code, switches the lights, and looks things up. The model behind him, the 125-billion-parameter
Qwen3.8-Flash-Next Coder, runs entirely on the home PC: an AMD RX 7600 XT graphics card with 16 GB (ROCm) plus
32 GB of system RAM. Your conversations stay at home.

<p align="center"><img src="docs/media/screens/web-desktop.png" alt="The web app: Ray's chat with his thinking and answer on the left, live GPU, VRAM, power and RAM monitor on the right" width="900"></p>

<table>
<tr>
<td align="center" width="33%"><img src="docs/media/screens/web-phone.png" alt="The web app on a phone: the chat with Ray" width="230"><br><b>Chat, on a phone</b></td>
<td align="center" width="33%"><img src="docs/media/screens/web-monitor.png" alt="The web app's monitor on a phone: speed, VRAM, GPU temperature, power, CPU and RAM" width="230"><br><b>Live monitor</b></td>
<td align="center" width="33%"><img src="docs/media/screens/android-drawer.png" alt="The Android app's voice drawer: Ray the panda listening, with a big orange mic button" width="230"><br><b>Android voice drawer</b></td>
</tr>
<tr>
<td align="center"><img src="docs/media/screens/android-about.png" alt="The Android app's About tab: the Ray on this phone card with the Android settings button and the Ok Ray switch" width="230"><br><b>"Ok Ray" and phone settings</b></td>
<td align="center"><img src="docs/media/screens/android-setup.png" alt="The Android app's setup screen: microphone, autostart, battery, notification access and screen reading, all ready" width="230"><br><b>Setup on the phone</b></td>
<td></td>
</tr>
</table>

## What Ray does

- **Talks with you.** Speak to him and he answers in his own voice. Speech recognition (Whisper) and his voice
  (Piper) run on the PC, so no audio goes to the cloud.
- **Codes with you.** One shared coding-agent session that you can use from the browser, the terminal and the
  phone. He reads and edits files, runs commands and tests, keeps checkpoints you can rewind, and remembers the plan.
  When he stays stuck, a DeepSeek helper can suggest the fix or write the patch (outside YOLO mode he asks first).
- **Lives on your phone.** An Android app holds the web app and adds a voice drawer. You can open it by holding the
  power button, with a Bluetooth headset or helmet button, or by saying "Ok Ray". He can also use the phone itself:
  battery, flashlight, alarms, media, notifications, the screen and the camera.
- **Runs the smart home.** He works lights, climate, plugs and sensors, 3D printers and cameras through Home
  Assistant.
- **Uses tools.** 40 tool servers, turned on only when a request needs them: web search, mail (with attachments)
  and drive, translation, maps, weather, papers and more.
- **Remembers.** Ray, Claude Code and Antigravity share one versioned memory store of decisions and preferences per
  project, and he keeps rules in code that no prompt can talk him out of (no git, no global memory, no phone camera
  unless you ask).
- **Shows his work.** You can watch the model think, follow each tool call, and see the GPU, memory and speed live.
- **Is tuned per model.** His behaviour settings (thinking level, when to nudge or call for help, result sizes) live
  in a profile per model, so tuning one model leaves the others as they are.
- **Is reachable from anywhere.** Remote access goes through a Cloudflare Tunnel behind a login.
- **Has a face.** A red panda drawn in dots sits on the input box. He puts a paw to his chin while thinking, moves
  with his voice, and takes cocoa breaks on long tasks ([meet him](docs/RAY_FEATURES.md#meet-ray)).

**Speed:** about **29 tokens per second** when chatting, **34 tok/s** in coding-agent sessions, and about
**370 tokens per second** when reading a long prompt (a 32K prompt is read in 87 s). Measured on the RX 7600 XT above
on 2026-11-21 at the card's everyday setting of 2500 MHz / 150 W (`tools/strata_bench.py --long`, medians of 3 runs).
The fastest runs, at 2800 MHz / 198 W before GPU crashes made the lower setting the everyday one, reached 383 tok/s
reading prompts. The full numbers are in [docs/RAY_SPEED.md](docs/RAY_SPEED.md).

## Quick start

You need Linux, a graphics card with 16 GB (AMD with ROCm, or NVIDIA), and 32 GB of RAM.

1. **Install Strata** and pick the Coder model: run `./setup.sh` (see [docs/INSTALL.md](docs/INSTALL.md); on AMD also
   [docs/AMD_HIP.md](docs/AMD_HIP.md)).
2. **Add your keys** to `~/.config/dl-ai/secrets.env` (at least `STRATA_API_KEY`). Nothing secret is stored in this
   repository.
3. **Start the server and Ray's session** as user services:

   ```sh
   cp tools/systemd/strata-server.service tools/systemd/dl-ai-sessiond.service ~/.config/systemd/user/
   # set the paths in both files to your checkout (and the server's to your run script), then:
   systemctl --user daemon-reload
   systemctl --user enable --now strata-server dl-ai-sessiond
   ```

4. **Copy Ray's settings profiles** (one per model, plus a base for every model):

   ```sh
   mkdir -p ~/.config/dl-ai/models && cp -n tools/model-profiles/*.json ~/.config/dl-ai/models/
   ```

5. **Open** `http://127.0.0.1:8080` and say hello.

The full setup (remote access, the commit hook, every command) is in [docs/RAY_SETUP.md](docs/RAY_SETUP.md).

### The Android app

The app is in [android/](android/). Copy `android/secrets.properties.example` to `android/secrets.properties`,
fill in your server's addresses and key, and build it with `./gradlew assembleDebug`. On the phone, make Ray the
digital assistant (Settings → Apps → Default apps), then open **About → Android settings** in the app to grant what
it needs.

## Learn more

| Page | What's in it |
| :--- | :--- |
| [Features](docs/RAY_FEATURES.md) | Ray's animations, the assistant, the coding agent, voice, smart home, every tool server |
| [Setup and use](docs/RAY_SETUP.md) | Installing step by step, remote access, the browser, terminal and API, all commands |
| [Speed](docs/RAY_SPEED.md) | Benchmarks on the RX 7600 XT and the settings behind them |
| [Upstream syncs](docs/RAY_CHANGES.md) | Which Strata releases were merged or ported, and when (fixes ported through 0.2.17) |
| [How Strata works](docs/HOW_IT_WORKS.md) | The engine underneath: experts, memory, speed tricks ([details](docs/DETAILS.md), [paper](docs/paper)) |

## Privacy and security

- **The model runs at home.** Prompts, answers and the model's thinking stay on the PC. Tools that use online
  services (web search, mail, translation, the DeepSeek helper) send them only what the task needs, and the DeepSeek
  helper asks you first outside YOLO mode.
- **No secrets in the repository.** Keys live in `~/.config/dl-ai/secrets.env`, and a commit hook blocks any commit
  that contains one.
- **Locked down by default.** The web app needs a login or the API key. The Android app gives its key, tools and
  microphone only to your own server's pages, and other apps on the phone can't use Ray's phone tools.

More detail is in the Security part of [docs/RAY_SETUP.md](docs/RAY_SETUP.md).

## Credits and license

Strata, the engine, the server and the installer, is by
[Niko1221 and the Strata contributors](https://github.com/Niko1221/Strata), under the MIT license. The model weights
are Qwen3.8-Flash-Next from Alibaba's Qwen team. Ray, D.L. CLI and the rest of this fork are by
[Damir](https://github.com/DamirLukina88). This fork is licensed under the
[MIT License with Attribution Requirement](LICENSE). Any fork, redistribution, or derivative work of this
repository must credit both upstream [Strata](https://github.com/Niko1221/Strata) (for core engine and architecture) and
[D.L. AI - Strata](https://github.com/DamirLukina88/D.L.-AI---Strata) (for fork development and features). Upstream's own
documentation is in [docs/](docs/), and its paper is in [docs/paper](docs/paper).
