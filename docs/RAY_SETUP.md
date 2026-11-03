# Ray: setup and use

Installing this fork on your own PC, and how to use it from the browser, the terminal and the API.

[← Back to the README](../README.md)

## Install

1. **Install Strata itself** as upstream describes it in [docs/INSTALL.md](INSTALL.md) (on AMD, see also
   [docs/AMD_HIP.md](AMD_HIP.md)). Use `./setup.sh` on Linux and pick the Coder model.

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
    `@path` reference to the prompt). **Sessions** opens the saved conversations, and **New** starts a new one (the
    current one is saved). From 1,200 px wide, Code and Monitor or About sit side by side with a draggable divider.
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
  | `/clear`, `/new` | start a new conversation; the current one is saved |
  | `/sessions [words]` | saved conversations, newest first; words search titles and messages |
  | `/resume N`, `/delete N` | bring a saved conversation back, or remove it from the list |
  | `/rename [N] <title>` | name this conversation, or saved conversation N |
  | `/prompts` | this conversation's prompts, numbered |
  | `/queue [rm N\|clear]` | list or remove messages queued while Ray is working |
  | `/edit N <text>`, `/rewind N`, `/branch N [text]` | replace prompt N, go back to before it, or branch from before it |
  | `!<command>` | run a shell command |

- **API:** the server speaks the OpenAI and Anthropic APIs on `/v1` (`/v1/chat/completions`, `/v1/audio/transcriptions`). Send the key as `Authorization: Bearer`.

## Security

- **No secrets in the repository.** Keys live in `~/.config/dl-ai/secrets.env`, and the pre-commit hook blocks a
  commit that contains one. It also blocks added lines that carry this machine's home path, the folder the checkout
  sits in, or the profile's email address; it reads those at run time, so the hook names none of them.
- **What goes online.** The model and its thinking stay on the PC. Tools that use online services send those services
  what a task needs: web search, Gmail, Google Drive, Proton Mail, DeepL, DeepSeek, and lookups such as weather or
  Wikipedia. DeepSeek, which gets your text for cloud reasoning, asks on a card before every call unless you typed
  `/mcp trust deepseek` for the session.
- **Browser requests** need a valid Cloudflare Access token (signature, issuer, audience and expiry are checked)
  or the API key. Keys are never accepted in URLs.
- **The session daemon** listens only on a Unix socket in your runtime directory (mode 600).
- **Workspace file access** is confined to the workspace directory.


## Running the tests

`tools/run_tests.sh` runs every suite of this fork the way each needs it (no GPU, model or running server needed):
the server tests, the tools tests one module at a time, and the web app's Node tests; `--android` adds the Android
app's unit tests and lint. It prints one line per suite. The engine's C++ tests are ctest (see
[AMD_HIP.md](AMD_HIP.md)).
