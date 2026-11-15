// serve/web/app-08-settings.js - part of the web app (see app-01-util.js): MCP servers, model settings, markdown, thinking and sampling.
// A classic script, loaded in order by index.html; it shares its globals with the others.
"use strict";

// ------------------------------------------------------------------ MCP servers (GET /mcp)
// Tools from the MCP servers in the run config: the chat offers them to the model (opt-in per request,
// "strata_mcp": true, which only this page sends); the Monitor lists the servers and what they offer.
let mcpInfo = {servers: [], tools: 0}, mcpRetry = null;
async function loadMcp() {
  try {
    const r = await fetch("mcp", {headers: headers()});
    if (!r.ok) return;
    mcpInfo = await r.json();
  } catch (e) { return; /* an older server: no MCP */ }
  renderMcp();
  clearTimeout(mcpRetry);                          // right after the start, servers may still be starting (npx downloads)
  if ((mcpInfo.servers || []).some((s) => s.status === "starting")) mcpRetry = setTimeout(loadMcp, 3000);
}
const MCP_STATE = {ready: ["st-badge--generating", "Connected"], starting: ["st-badge--reading", "Starting"],
                   failed: ["st-badge--error", "Failed"], stopped: ["st-badge--queued", "Stopped"], idle: ["", "Waiting"]};
function renderMcp() {
  const servers = mcpInfo.servers || [];
  $("mcp-card").hidden = !servers.length;
  const ready = servers.filter((s) => s.status === "ready" || s.status === "stopped");
  $("mcp-sum").textContent = servers.length ? `${fmt(mcpInfo.tools)} tools · ${ready.length} of ${servers.length} servers connected` : "";
  $("mcp-list").innerHTML = servers.map((s) => {
    const [cls, text] = MCP_STATE[s.status] || ["", s.status];
    const info = s.info && s.info.name ? ` · ${s.info.name}${s.info.version ? ` ${s.info.version}` : ""}` : "";
    return `<div class="mcp-server"><div class="mcp-server__head"><span class="st-badge ${cls}">${esc(text)}</span>` +
      `<strong>${esc(s.name)}</strong><span class="muted small">${esc(s.transport)} · ${fmt(s.tools.length)} tools${esc(info)}</span></div>` +
      (s.error ? `<div class="msg-error">${esc(s.error)}</div>` : "") +
      (s.tools.length ? `<div class="mcp-server__tools">${s.tools.map((t) => `<span class="chip" title="${esc(t.description || "")}">${esc(t.tool)}</span>`).join("")}</div>` : "") +
      `</div>`;
  }).join("");
}

// ------------------------------------------------------------------ Model settings (GET / POST /config, #564)
// A few documented keys of the run config (strata-<model>.json), for every client, from the next start on.  The
// server lists them, checks every value and keeps every other key of the file as it is.
let cfgKeys = [];
async function loadConfig() {
  let r;
  try { r = await fetch("config", {headers: headers()}); } catch (e) { return; }
  if (!r.ok) { $("cfg-card").hidden = true; return; }       // no run config, an older server, or no key yet
  const c = await r.json();
  cfgKeys = c.keys || [];
  $("cfg-file").textContent = c.file || "";
  $("cfg-form").innerHTML = cfgKeys.map((k, i) => {
    const id = `cfg-${i}`, v = k.value;
    let input;
    if (k.kind === "bool" || k.kind === "enum") {
      const opts = k.kind === "bool" ? [["true", "on"], ["false", "off"]] : k.choices.map((x) => [x, x]);
      const cur = v == null ? "" : String(v);
      input = `<select class="st-input" id="${id}"><option value=""${cur === "" ? " selected" : ""}>default</option>` +
        opts.map(([val, text]) => `<option value="${esc(val)}"${cur === val ? " selected" : ""}>${esc(text)}</option>`).join("") + `</select>`;
    } else {
      const text = v == null ? "" : Array.isArray(v) ? v.join(", ") : String(v);
      input = `<input class="st-input" id="${id}" ${k.kind === "number" ? 'type="number" step="any" min="0"' : 'type="text"'} ` +
        `value="${esc(text)}" placeholder="default" autocomplete="off">`;
    }
    return `<label for="${id}" title="${esc(k.help)}">${esc(k.help)}<code>${esc(k.key)}</code></label>${input}`;
  }).join("");
  $("cfg-card").hidden = false;
}
function configValue(k, el) {
  const s = el.value.trim();
  if (s === "") return null;
  if (k.kind === "bool") return s === "true";
  if (k.kind === "number") return Number(s);
  return s;                                         // enum, or names (the server splits them at commas)
}
$("cfg-save").addEventListener("click", async () => {
  const set = {};
  cfgKeys.forEach((k, i) => {
    const v = configValue(k, $(`cfg-${i}`));
    const old = Array.isArray(k.value) ? k.value.join(", ") : k.value;
    if (JSON.stringify(v) !== JSON.stringify(old ?? null)) set[k.key] = v;
  });
  if (!Object.keys(set).length) { $("cfg-msg").textContent = "Nothing changed."; return; }
  try {
    const r = await fetch("config", {method: "POST", headers: headers(true), body: JSON.stringify({set})});
    const b = await r.json();
    if (!r.ok) throw new Error((b.error || {}).message || `HTTP ${r.status}`);
    $("cfg-msg").textContent = b.changed.length
      ? `Saved (${b.changed.join(", ")}); the earlier file is ${b.file}.bak. Start the model again to use it.` : "Nothing changed.";
    loadConfig();
  } catch (e) {
    $("cfg-msg").textContent = "";
    toast("error", "Not saved", String(e.message || e), 6000);
  }
});

// ------------------------------------------------------------------ Markdown (escaped first, then formatted)
function inline(s) {
  const codes = [];
  s = s.replace(/`([^`\n]+)`/g, (_, c) => { codes.push(c); return `\u0000${codes.length - 1}\u0000`; });
  s = esc(s)
    .replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*\w])\*([^*\n]+)\*(?![*\w])/g, "$1<em>$2</em>")
    .replace(/\[([^\]\n]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  return s.replace(/\u0000(\d+)\u0000/g, (_, i) => `<code class="inline">${esc(codes[+i])}</code>`);
}
function codeBlock(lang, code) {
  return `<div class="st-code"><div class="st-code__head"><span>${esc(lang || "code")}</span>` +
    `<button class="st-btn st-btn--icon" data-code-copy aria-label="Copy code">${icon("copy")}</button></div>` +
    `<pre><code>${esc(code)}</code></pre></div>`;
}
function blocks(text) {
  const out = [], lines = text.split("\n");
  let para = [], list = null;
  const flushPara = () => {
    if (!para.length) return;
    // CommonMark / GFM soft breaks: single newlines become spaces; two spaces or backslash at line end produce hard breaks (#3818)
    const parts = [];
    for (let p = 0; p < para.length; p++) {
      const line = para[p];
      const hard = /( {2,}|\\)$/.test(line);
      parts.push(inline(line.replace(/( {2,}|\\)$/, "")));
      if (p < para.length - 1) parts.push(hard ? "<br>" : " ");
    }
    out.push(`<p>${parts.join("")}</p>`);
    para = [];
  };
  const flushList = () => { if (list) out.push(`<${list.tag}>${list.items.map((i) => `<li>${inline(i)}</li>`).join("")}</${list.tag}>`); list = null; };
  for (let i = 0; i < lines.length; i++) {
    const l = lines[i];
    let m;
    if (!l.trim()) { flushPara(); flushList(); continue; }
    if ((m = l.match(/^(#{1,6})\s+(.*)$/))) { flushPara(); flushList(); out.push(`<${m[1].length <= 2 ? "h3" : "h4"}>${inline(m[2])}</${m[1].length <= 2 ? "h3" : "h4"}>`); continue; }
    if (/^\s*([-*_])\s*\1\s*\1[\s\1]*$/.test(l)) { flushPara(); flushList(); out.push("<hr>"); continue; }
    if ((m = l.match(/^>\s?(.*)$/))) { flushPara(); flushList(); out.push(`<blockquote>${inline(m[1])}</blockquote>`); continue; }
    if (/^\s*\|.*\|\s*$/.test(l) && i + 1 < lines.length && /^\s*\|?[\s:-]+\|[\s|:-]*$/.test(lines[i + 1])) {
      flushPara(); flushList();
      const cells = (row) => row.trim().replace(/^\||\|$/g, "").split("|").map((c) => inline(c.trim()));
      let html = `<table><thead><tr>${cells(l).map((c) => `<th>${c}</th>`).join("")}</tr></thead><tbody>`;
      i += 2;
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) html += `<tr>${cells(lines[i++]).map((c) => `<td>${c}</td>`).join("")}</tr>`;
      i--;
      out.push(html + "</tbody></table>");
      continue;
    }
    if ((m = l.match(/^\s*(?:[-*+]|(\d+)[.)])\s+(.*)$/))) {
      flushPara();
      const tag = m[1] ? "ol" : "ul";
      if (!list || list.tag !== tag) { flushList(); list = {tag, items: []}; }
      list.items.push(m[2]);
      continue;
    }
    if (list && /^\s{2,}\S/.test(l)) { list.items[list.items.length - 1] += " " + l.trim(); continue; }
    flushList();
    para.push(l);
  }
  flushPara(); flushList();
  return out.join("");
}
function markdown(text) {
  let html = "", rest = text;
  for (;;) {
    const m = rest.match(/(^|\n)```([^\n`]*)\n/);
    if (!m) { html += blocks(rest); break; }
    html += blocks(rest.slice(0, m.index));
    rest = rest.slice(m.index + m[0].length);
    const end = rest.match(/(^|\n)```[ \t]*(\n|$)/);
    if (!end) { html += codeBlock(m[2].trim(), rest); break; }         // still streaming
    html += codeBlock(m[2].trim(), rest.slice(0, end.index));
    rest = rest.slice(end.index + end[0].length);
  }
  return html;
}

// ------------------------------------------------------------------ settings (thinking and sampling, shared with the CLI)
const DEFAULTS = {thinking: "auto", temperature: 0.6, top_p: 0.95, top_k: 20, seed: "", esp: true};
let settings = {...DEFAULTS, ...store.get("sampling", {})};

// ------------------------------------------------------------------ the sampling drawer
let lastDrawerTrigger = null;
function openDrawer(open) {
  const drawer = $("drawer");
  if (!drawer) return;
  if (open) {
    if (document.activeElement && (document.activeElement.id === "sampling-btn" || document.activeElement.id === "code-sampling-btn")) {
      lastDrawerTrigger = document.activeElement;
    }
    drawer.dataset.open = "true";
    drawer.removeAttribute("aria-hidden");
    drawer.removeAttribute("inert");
    drawer.inert = false;
    $("scrim").hidden = false;
    loadDrawer();
    syncShared().then(loadDrawer);
    loadMcp();
  } else {
    // Release focus from any focused element inside drawer before setting aria-hidden/inert
    if (document.activeElement && drawer.contains(document.activeElement)) {
      document.activeElement.blur();
      if (lastDrawerTrigger && typeof lastDrawerTrigger.focus === "function") {
        try { lastDrawerTrigger.focus(); } catch (_) {}
      } else if (shown("code") && $("code-mobile-input")) {
        try { $("code-mobile-input").focus(); } catch (_) {}
      }
    }
    drawer.dataset.open = "false";
    drawer.setAttribute("aria-hidden", "true");
    drawer.setAttribute("inert", "");
    drawer.inert = true;
    $("scrim").hidden = true;
  }
}
function loadDrawer(s = settings) {
  const eff = (code.state && code.state.effort) || s.thinking || "auto";
  for (const b of $("s-thinking").children) b.setAttribute("aria-checked", String(b.dataset.v === eff));
  $("s-temp").value = s.temperature; $("s-topp").value = s.top_p; $("s-topk").value = s.top_k;
  $("s-seed").value = s.seed;
  $("s-esp").setAttribute("aria-checked", String(s.esp !== false));
  $("esp-row").hidden = !projectionLoaded();
  outputs();
}
// D.L. AI: the Chat settings live on the server (GET/POST /settings), so every browser and the CLI (Code tab, terminal),
// which sends no sampling fields of its own, use the same ones.  The server's copy wins; with none yet, this browser's
// settings are published.
function fromShared(d) {
  const stored = store.get("sampling", {});
  return {thinking: stored.thinking || (d.reasoning_effort === "high" ? "auto" : d.reasoning_effort) || DEFAULTS.thinking,
          temperature: d.temperature ?? DEFAULTS.temperature,
          top_p: d.top_p ?? settings.top_p, top_k: d.top_k ?? settings.top_k,
          seed: d.seed != null ? String(d.seed) : "",
          esp: d.experimental_speed_projection ?? settings.esp};
}
async function syncShared() {
  try {
    const r = await fetch("settings", {headers: headers()});
    if (!r.ok) return;                                   // no key yet, or an older server
    const j = await r.json();
    if (j.shared && j.defaults) {
      settings = {...settings, ...fromShared(j.defaults)};
      store.set("sampling", settings);
    } else {
      await saveShared(settings);
    }
  } catch (e) { /* offline: keep this browser's copy */ }
}
function sharedDefaults(s) {
  const d = {reasoning_effort: (s.thinking && s.thinking !== "auto") ? s.thinking : "high", temperature: +s.temperature};
  if (+s.temperature > 0) Object.assign(d, {top_p: +s.top_p, top_k: +s.top_k});
  if (s.seed) d.seed = +s.seed;
  if (projectionLoaded()) d.experimental_speed_projection = s.esp !== false;
  return d;
}
async function saveShared(s) {
  const r = await fetch("settings", {method: "POST", headers: headers(true),
                                      body: JSON.stringify({defaults: sharedDefaults(s)})});
  if (!r.ok) {
    let msg = `HTTP ${r.status}`;
    try { msg = (await r.json()).error.message || msg; } catch (e) { /* not json */ }
    throw new Error(msg);
  }
}
// the engine was started with the experimental-speed-projection control vector (INFO cvec=...)
function projectionLoaded() {
  const eng = lastMetrics && lastMetrics.engine ? lastMetrics.engine : {};
  if (eng.cvec_configured) return true;                  // D.L. AI: lazy load, the model is not in memory yet
  const c = eng.cvec || 0;
  return !!c && c !== "0";
}
function outputs() {
  const t = +$("s-temp").value;
  $("o-temp").textContent = t === 0 ? "0 · greedy" : t.toFixed(2);
  $("o-topp").textContent = (+$("s-topp").value).toFixed(2);
  $("o-topk").textContent = $("s-topk").value;
  const sel = [...$("s-thinking").children].find((b) => b.getAttribute("aria-checked") === "true");
  $("o-thinking").textContent = sel ? {auto: "auto per turn (default)", none: "answers right away", low: "short", medium: "medium", high: "thorough"}[sel.dataset.v] : "";
  for (const id of ["s-topp", "s-topk"]) $(id).disabled = t === 0;
}
for (const b of $("s-thinking").children) b.onclick = () => { for (const x of $("s-thinking").children) x.setAttribute("aria-checked", String(x === b)); outputs(); };
for (const id of ["s-temp", "s-topp", "s-topk"]) $(id).oninput = outputs;
$("s-esp").onclick = () => $("s-esp").setAttribute("aria-checked", String($("s-esp").getAttribute("aria-checked") !== "true"));
// the recommended coding-agent settings (DEFAULTS), applied and saved for Chat and the CLI at once
$("s-reset").onclick = () => { loadDrawer(DEFAULTS); $("s-apply").click(); };
$("s-apply").onclick = async () => {
  const sel = [...$("s-thinking").children].find((b) => b.getAttribute("aria-checked") === "true");
  const thinking = sel ? sel.dataset.v : "auto";
  settings = {thinking, temperature: +$("s-temp").value, top_p: +$("s-topp").value,
              top_k: +$("s-topk").value, seed: $("s-seed").value.trim(),
              esp: $("s-esp").getAttribute("aria-checked") === "true"};
  store.set("sampling", settings);
  openDrawer(false);
  try {
    await saveShared(settings);
  } catch (e) {
    toast("error", "Saved here, but not on the server", `The CLI keeps the previous settings: ${e.message}`, 6000);
    return;
  }
  try {
    await codeOp("input", { text: `/effort ${thinking}` });
  } catch (_) {}
  toast("success", "Sampling saved", (settings.temperature === 0 ? "Greedy: the same question gives the same answer. " : "") +
        `Thinking set to ${thinking}.`);
};
