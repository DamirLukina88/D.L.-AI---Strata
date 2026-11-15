# Security

## Reporting a vulnerability

Please report anything that should not be public until it is fixed **privately**, through GitHub's private
vulnerability reporting: the repository's **Security** tab, **Report a vulnerability**
([direct link](https://github.com/Niko1221/Strata/security/advisories/new)). Say what you found, how to reproduce it
(the request, the config keys involved, the Strata version), and what an attacker gains. We answer there, fix it in
a release, and credit you in the advisory unless you ask us not to.

Ordinary hardening ideas and findings that are safe to discuss in public are welcome as an
[issue](https://github.com/Niko1221/Strata/issues) (#544 collects audit findings) or as a pull request, which we
review like our own code.

Supported: the latest release. Fixes go into the next release, not into older ones.

## Reporting a problem in this fork (Ray)

Findings about the parts this fork adds (Ray's agent, the session daemon, the web app's Code tab, the Android app,
the phone and MCP tools) go to the fork's owner, [DamirLukina88](https://github.com/DamirLukina88), through the fork's
GitHub private vulnerability reporting, not to upstream. Upstream's engine and server are covered by the policy above.

What the fork adds to the attack surface:

- **The session daemon** listens only on a Unix socket in the user's runtime directory (mode 600). The web app reaches
  it through the server, which checks the caller first.
- **Remote access** is a Cloudflare Tunnel; browser requests need a valid Cloudflare Access token (signature, issuer,
  audience and expiry are checked on every request) or the API key. Keys are never accepted in URLs.
- **Rules in code, not in the prompt.** The agent cannot use git, change global memory, use the phone's camera, media
  or clipboard, or open a desktop window unless the request's words ask, in YOLO too (`agent_boundary`,
  `tools/dl_boundary.py`; `dl_mcp.DEFAULT_ASK_WORDS`). Credentials in an email, file or URL argument are refused
  before any approval card.
- **Text from web pages, mail, Drive and memory pages is data**, never instructions to the agent.
- **No secrets in the repository.** Keys live in `~/.config/dl-ai/secrets.env`, each MCP server gets only the keys it
  names, and a pre-commit hook blocks a commit that adds a key, a home path or a personal address.
- **Workspace file access** (upload, download, list) is confined to the workspace directory.

## What the server exposes

Strata runs a model on your PC and serves it over HTTP (`serve/server.py`). Out of the box it is reachable from
this PC only. The details and every setting are in [docs/DETAILS.md](docs/DETAILS.md) ("From other devices",
"Host names", "Web pages without an API key", "Tools from MCP servers").

- **Where it listens.** `127.0.0.1` by default. `--host 0.0.0.0` (or `"host"` in `strata-<model>.json`) opens it to
  your network, and the server then warns when no API key is set.
- **API key.** `"api_key"` in the run config (or `STRATA_API_KEY`) is required on `/v1/*` and on every endpoint
  that shows the model's state, requests or answers (`/status`, `/metrics`, `/settings`, `/mcp`, `/props`, `/slots`,
  `/api/requests`, `/config`) and on every `POST`. It is compared in constant time. Set one before you open the
  server to your network or put a tunnel in front of it.
- **Host check (DNS rebinding, 0.1.38).** Without an API key the server answers only requests whose `Host` is a name
  it knows (`localhost`, an IP address, the address it listens on and, when it listens beyond this PC, this PC's
  name). Others get 403. `"allowed_hosts"` adds names; with an API key the key decides.
- **Origin check (0.1.38).** Without an API key, a browser `POST` to `/v1/*` from another web site's page (it carries
  an `Origin` header) gets 403 unless that origin is Strata's own page, `localhost`, an allowed host, or listed in
  `"trusted_origins"` / `"cors_origins"`. Changing settings (`/settings`, and `/config`: the few run config keys the
  page's Model settings may change - never the network, key, MCP or program keys), `/load` and `/unload` and the
  MCP tools are accepted only as JSON from Strata's own page (or `"trusted_origins"`), so a page elsewhere cannot
  change settings or run tools.
- **CORS** is off unless `"cors_origins"` lists origins, and then only for `/v1/*`.
- **MCP tools** are opt-in: only the servers you put in the run config, only for requests from Strata's own page
  that ask for them. They run with your user's rights, and the model decides when to call them.
- **The request monitor** (`/api-monitor`, which keeps the last prompts and answers in memory) is off unless
  `"api_monitor": true` is set. Apart from it, the server keeps in its process memory the text and tokens of its
  last few prompts, whatever `"api_monitor"` says, to encode the next turn faster; no endpoint shows them, and they
  are gone when the server stops.

Strata has not had an outside security audit yet.
