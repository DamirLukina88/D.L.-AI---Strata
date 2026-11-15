// serve/web/app-05-code.js - part of the web app (see app-01-util.js): Code: the shared CLI session, and saved sessions.
// A classic script, loaded in order by index.html; it shares its globals with the others.
"use strict";

// ------------------------------------------------------------------ Code: shared CLI session (tools/dl_sessiond.py)
// The same session runs in the terminal (dl_cli.py --attach): this tab is one more client of it.
// ?session=NAME shows another daemon session (the agent bench's bench-* sessions); the default is the shared one
const CODE_SESSION = /^[A-Za-z0-9_.-]{1,64}$/.test(new URLSearchParams(location.search).get("session") || "")
  ? new URLSearchParams(location.search).get("session") : "dl-ai-code";
const code = { conn: null, state: {}, client: "", cur: null, retry: 0, renderQueued: false, approvals: {}, turnFromVoice: false, replaying: false, lastSpokenText: "" };
// thinking blocks start open; the ones you close stay closed (per session, kept in this browser)
const thinkClosedKey = `code.thinkClosed.${CODE_SESSION}`;
const codeThinkClosed = new Set(store.get(thinkClosedKey, []));
function codeSaveThinkState() { store.set(thinkClosedKey, [...codeThinkClosed].slice(-500)); }

function codeFeed() { return $("code-mobile-messages"); }
// a box with its own scroll bar (the thinking text) follows new text while you are at its bottom; scrolled up, it stays
function followText(box, text) {
  const atEnd = box.scrollHeight - box.scrollTop - box.clientHeight < 24;
  box.textContent = text;
  if (atEnd) box.scrollTop = box.scrollHeight;
}
// The feed follows the answer while the reader has not left (#4014, from upstream 0.2.7). Asking "within 80 px of the
// bottom?" pulled the view back after every wheel notch (about 100 px) while text streamed in; now the reader's own input
// (wheel up, a finger, a key moving up, the scrollbar) lets go at once, and a scroll back to the bottom follows again.
const FOLLOW_SLACK = 24, FAR_AWAY = 400, INPUT_WINDOW_MS = 400;
let codeStick = true, codeLastInput = 0;
function followAfterScroll(distance, wasFollowing, msSinceInput) {
  if (distance <= FOLLOW_SLACK) return true;
  if (msSinceInput <= INPUT_WINDOW_MS || distance > FAR_AWAY) return false;
  return wasFollowing;
}
function codeAtBottom() { return codeStick; }
function codeScroll(force) {
  const f = codeFeed();
  if (!f) return;
  if (force) codeStick = true;
  if (codeStick) f.scrollTop = f.scrollHeight;
}
(function watchCodeReader() {
  const f = codeFeed();
  if (!f) return;
  const touch = () => { codeLastInput = Date.now(); };
  f.addEventListener("wheel", (e) => { touch(); if (e.deltaY < 0 && f.scrollTop > 0) codeStick = false; }, { passive: true });
  f.addEventListener("touchmove", touch, { passive: true });
  f.addEventListener("pointerdown", touch, { passive: true });
  f.addEventListener("keydown", (e) => {
    touch();
    if (["PageUp", "ArrowUp", "Home"].includes(e.key) && f.scrollTop > 0) codeStick = false;
  });
  f.addEventListener("scroll", () => {
    codeStick = followAfterScroll(f.scrollHeight - f.scrollTop - f.clientHeight, codeStick, Date.now() - codeLastInput);
  }, { passive: true });
})();

// "Reading the prompt… 42 s (61%)": one line in the feed while the engine reads a long prompt (an image, a big file),
// rewritten in place and gone when the answer starts (dl_cli.stream_chat_turn's progress events; never replayed)
function codeReading(ev) {
  const el = codeFeed().querySelector(".cs-reading");
  if (!ev || ev.phase !== "reading") { if (el) el.remove(); return; }
  const pct = ev.total && ev.read != null ? ` (${Math.round((100 * ev.read) / ev.total)}%)` : "";
  const text = `Reading the prompt… ${ev.elapsed_s || 0} s${pct}${ev.slow ? " · unusually slow" : ""}`;
  if (el) el.textContent = text;
  else codeCard("cs-notice cs-notice--info cs-reading", esc(text));
}

function codeCard(cls, html) {
  const el = document.createElement("div");
  el.className = `code-mobile-card ${cls}`;
  el.innerHTML = html;
  const stick = codeAtBottom();
  codeFeed().appendChild(el);
  if (stick) codeScroll(true);
  return el;
}

function codeAssistant() {
  if (code.cur) return code.cur;
  const el = codeCard("code-mobile-card--assistant cs-reply",
    `<details class="cs-think" hidden open><summary>Thinking</summary><div class="cs-think-body"></div></details><div class="cs-text md"></div>` +
    `<div class="code-card-actions">` +
    `<button type="button" class="st-btn st-btn--icon st-btn--sm code-card-action" data-code-copy title="Copy answer" aria-label="Copy answer">${icon("copy")}</button>` +
    `<button type="button" class="st-btn st-btn--icon st-btn--sm code-card-action" data-code-speak title="Read aloud" aria-label="Read aloud">${icon("volume")}</button>` +
    `</div>`);
  code.cur = { el, thinking: "", text: "", fromVoice: Boolean(code.turnFromVoice) };
  return code.cur;
}

function codeEnd() {                                      // close the open reply block, drawn in full
  if (code.cur) {
    const cur = code.cur;
    codeRenderCur(cur);
  }
  code.cur = null;
}

// the turn's SpeakStream (web/speakstream.js): started by the reply's first text, it queues pieces on TTSController
function codeSpeech() {
  if (code.speech) return code.speech;
  const queue = TTSController.streamStart();
  let segStart = 0;
  const ss = new SpeakStream({
    say: (text) => {
      if (queue !== TTSController.queue) return;                 // stopped, or another reading took over
      if (ss.segSpoken === 0) segStart = queue.length;
      TTSController.streamSay(text);
    },
    drop: (keep) => { if (queue === TTSController.queue) TTSController.streamDrop(segStart + keep); },
  });
  ss.timer = setInterval(() => ss.tick(), 1000);
  code.speech = ss;
  return ss;
}

function codeSpeechEnd() {
  const ss = code.speech;
  if (!ss) return false;
  code.speech = null;
  clearInterval(ss.timer);
  ss.end();
  TTSController.streamEnd();
  return true;
}

function codeOnTurnEnd() {
  if (codeSpeechEnd()) {                                         // read while it was written
    const cards = codeFeed() ? codeFeed().querySelectorAll(".code-mobile-card--assistant") : [];
    const last = cards.length && cards[cards.length - 1].querySelector(".cs-text, .code-mobile-card-body");
    if (last) code.lastSpokenText = (last.innerText || last.textContent || "").trim();
  } else if (TTSController.willAutoSpeak() && code.turnFromVoice && !code.replaying) {
    const cards = codeFeed() ? codeFeed().querySelectorAll(".code-mobile-card--assistant") : [];
    if (cards.length) {
      const lastCard = cards[cards.length - 1];
      const textEl = lastCard.querySelector(".cs-text") || lastCard.querySelector(".code-mobile-card-body");
      const sp = lastCard.querySelector("[data-code-speak]");
      if (textEl) {
        const textToSpeak = (textEl.innerText || textEl.textContent || "").trim();
        if (textToSpeak && textToSpeak !== code.lastSpokenText) {
          code.lastSpokenText = textToSpeak;
          TTSController.speakText(textToSpeak, sp);
        }
      }
    }
  }
  code.turnFromVoice = false;
  if (typeof RayFace !== "undefined" && !TTSController.speaking) RayFace.end(false);   // thought, but nothing to say
}

function codeRenderCur(block) {
  code.renderQueued = false;
  const c = block || code.cur;
  if (!c) return;
  const stick = codeAtBottom();
  const think = c.el.querySelector(".cs-think");
  if (c.thinking) { think.hidden = false; followText(think.querySelector(".cs-think-body"), c.thinking); }
  c.el.querySelector(".cs-text").innerHTML = c.text ? markdown(c.text) : "";
  if (stick) codeScroll(true);
}
function codeQueueRender() {
  if (!code.renderQueued) { code.renderQueued = true; requestAnimationFrame(() => codeRenderCur()); }
}

function codeBar(label, used, total, pct) {
  const level = pct >= 90 ? "bad" : pct >= 75 ? "warn" : "ok";
  return `<div class="cs-bar"><span class="cs-bar-label">${esc(label)}</span>
    <span class="cs-bar-track"><span class="cs-bar-fill cs-bar-fill--${level}" style="width:${Math.min(100, pct).toFixed(1)}%"></span></span>
    <span class="cs-bar-val">${used.toFixed(1)} / ${total.toFixed(1)} GB</span></div>`;
}

function codeHealth(d) {
  const eng = d.engine || d.strata || {};
  const rows = [
    d.ram ? codeBar("RAM", d.ram.used_gb, d.ram.total_gb, d.ram.pct) : "",
    d.vram ? codeBar("VRAM", d.vram.used_gb, d.vram.total_gb, d.vram.pct) : "",
    d.swap ? codeBar("Swap", d.swap.used_gb, d.swap.total_gb, d.swap.pct) : "",
  ].join("");
  const cpu = d.cpu ? `<div class="cs-kv"><span>CPU load</span><span>${(d.cpu.load_1m || 0).toFixed(2)} (${d.cpu.cores} cores)</span></div>` : "";
  const engine = eng.status ? `<div class="cs-kv"><span>Engine</span><span>${esc(eng.status)} ${esc(eng.model || "")}</span></div>` : "";
  return `<div class="code-mobile-card-header"><span class="role-tag">System health</span></div>${rows}${cpu}${engine}`;
}

function codeApprovalCard(ev) {
  // "mcp-always": sending email or sharing - the whole message is shown (a YOLO session never asks)
  const mail = ev.kind === "mcp-always";
  const [reason, foreign] = String(ev.reason || "").split(" · ADDRESS NOT FROM YOU: ");
  const el = codeCard("cs-approval", (mail ? `
    <div class="cs-approval-title">${/^scheduled/.test(reason) ? "⏰ Schedule this?" : /permission|access|share/i.test(String(ev.summary).split("\n")[0]) ? "🔗 Share this?" : "✉ Send this?"}</div>
    <pre class="cs-approval-mail">${esc(ev.summary)}</pre>
    <div class="cs-approval-reason">${esc(reason)}${foreign ? ` · <span class="cs-approval-foreign">address not from you: ${esc(foreign)}</span>` : ""}</div>` : `
    <div class="cs-approval-title">${ev.kind === "plan" ? "📋" : "⚠"} ${esc(ev.summary)}</div>
    <div class="cs-approval-reason">${esc(ev.reason || "")}</div>`) + `
    <div class="cs-approval-actions">
      <button type="button" class="st-btn st-btn--primary st-btn--sm" data-ok="1">${ev.kind === "plan" ? "Execute" : "Approve"}</button>
      <button type="button" class="st-btn st-btn--secondary st-btn--sm" data-ok="0">${ev.kind === "plan" ? "Keep planning" : "Deny"}</button>
    </div>`);
  for (const b of el.querySelectorAll("button")) {
    b.onclick = () => codeOp(b.dataset.ok === "1" ? "approve" : "deny", { id: ev.id });
  }
  code.approvals[ev.id] = el;
}

function codeResolve(id, ok) {
  const el = code.approvals[id];
  if (!el) return;
  el.classList.add("cs-approval--done");
  const act = el.querySelector(".cs-approval-actions");
  if (act) act.innerHTML = `<span class="muted small">${ok ? "Approved" : "Not approved"}</span>`;
  delete code.approvals[id];
}

// The active plan (PLAN.md) the done check holds the agent to: "PLAN 12/34", red when it has a Blocked: line.
function codePlanChip(plan) {
  if (!plan) return "";
  const total = (plan.done || 0) + (plan.open || 0);
  const label = plan.blocked ? "BLOCKED" : `PLAN ${plan.done || 0}/${total}`;
  const tip = `${plan.file}: ${plan.done || 0} steps done, ${plan.open || 0} open` + (plan.blocked ? ", blocked" : "");
  return ` <span class="cs-mode cs-mode--progress${plan.blocked ? " cs-mode--blocked" : ""}" title="${esc(tip)}">${esc(label)}</span>`;
}

function codeRenderQueued(queued) {
  const bar = $("code-queued-bar");
  if (!bar) return;
  const list = Array.isArray(queued) ? queued : [];
  if (!list.length) {
    bar.hidden = true;
    bar.innerHTML = "";
  } else {
    bar.hidden = false;
    bar.innerHTML = list.map((q, i) => {
      const label = list.length > 1 ? `QUEUED ${i + 1}` : "QUEUED";
      return `<div class="code-queued-item" data-queue-id="${esc(q.id)}">
        <span class="cs-mode cs-mode--queued" title="Sent at the next step (after the current tool or turn)">${label}</span>
        <span class="code-queued-text" title="${esc(q.text || "")}">${esc(q.text || "")}</span>
        <div class="code-queued-actions">
          <button type="button" class="st-btn st-btn--secondary st-btn--sm code-queued-btn" data-queue-now="${esc(q.id)}" title="Interrupt the current step and send this now">Send now</button>
          <button type="button" class="st-btn st-btn--icon st-btn--sm code-card-action" data-queue-edit="${esc(q.id)}" data-queue-text="${esc(q.text || "")}" title="Edit (move back to the input box)" aria-label="Edit queued message">✎</button>
          <button type="button" class="st-btn st-btn--icon st-btn--sm code-card-action" data-queue-del="${esc(q.id)}" title="Remove from queue" aria-label="Remove queued message">✕</button>
        </div>
      </div>`;
    }).join("");
  }
  const rf = $("ray-face"), comp = document.querySelector(".code-mobile-composer");
  if (rf && comp && !rf.hidden) rf.style.setProperty("--ray-face-bottom", `${comp.offsetHeight - 3}px`);
}

$("code-queued-bar")?.addEventListener("click", async (e) => {
  const nowBtn = e.target.closest("[data-queue-now]");
  if (nowBtn) {
    await codeOp("interrupt", { id: nowBtn.dataset.queueNow });
    return;
  }
  const editBtn = e.target.closest("[data-queue-edit]");
  if (editBtn) {
    const fallbackText = editBtn.dataset.queueText || "";
    const res = await codeOp("input", { text: `/queue_delete ${editBtn.dataset.queueEdit}` });
    if (!res) return;
    const ta = $("code-mobile-input");
    if (ta) {
      const restored = res.item?.text || fallbackText;
      ta.value = ta.value.trim() ? `${restored}\n${ta.value}` : restored;
      ta.dispatchEvent(new Event("input"));
      ta.focus();
    }
    return;
  }
  const delBtn = e.target.closest("[data-queue-del]");
  if (delBtn) {
    await codeOp("input", { text: `/queue_delete ${delBtn.dataset.queueDel}` });
  }
});

function codeSetState(st) {
  code.state = st || {};
  const meta = $("code-scaffold-meta");
  if (meta) {
    const mode = (code.state.mode || "act").toUpperCase();
    const eff = code.state.effort ? ` <span class="cs-mode cs-mode--effort" title="Thinking level: ${esc(code.state.effort)}">${esc(code.state.effort.toUpperCase())}</span>` : "";
    meta.innerHTML = `<span class="cs-mode cs-mode--${esc(code.state.mode || "act")}">${mode}</span>` +
      eff +
      (code.state.yolo ? ` <span class="cs-mode cs-mode--yolo">YOLO</span>` : "") +
      codePlanChip(code.state.plan) +
      (code.state.mcp || []).map((m) => ` <span class="cs-mode cs-mode--mcp" title="${esc(m.description)} (${esc(m.why || "on")})">${esc(m.name)}</span>`).join("") +
      ` <code title="${esc(code.state.workspace || "")}">${esc((code.state.workspace || "").split("/").slice(-2).join("/"))}</code>`;
  }
  codeRenderQueued(code.state.queued);
  const busy = !!code.state.busy;
  if ($("code-stop-btn")) $("code-stop-btn").hidden = !busy;
  // Ray thinks while the session works on a turn: he appears when it gets busy. A typed turn's answer sends him away
  // (codeEvent); a spoken one keeps him until he reads it aloud (codeOnTurnEnd); this catches a turn with nothing to say
  if (typeof RayFace !== "undefined" && busy !== code.wasBusy) {
    if (busy) {
      if (modelUnloaded) {
        modelLoading = true;
        setPill("reading", "Loading model…");
      } else if (TTSController.isThinkAllOn() && TTSController.isOrbOn()) {
        RayFace.thinking();
      }
    } else {
      setTimeout(() => { if (!TTSController.speaking && RayFace.state.mode === "think") RayFace.end(false); }, 400);
    }
  }
  code.wasBusy = busy;
  codeBarFit();
  document.querySelector(".code-dot")?.classList.toggle("code-dot--busy", busy);
}

// The session line in the Code bar goes to a row of its own when it would be cut (a narrow side-by-side pane, many
// MCP chips): measured in its one-row form, so it moves back up as soon as there is room again.
function codeBarFit() {
  const bar = document.querySelector(".code-terminal-bar"), meta = $("code-scaffold-meta");
  if (!bar || !meta) return;
  bar.classList.remove("code-terminal-bar--stacked");
  if (meta.scrollWidth > meta.clientWidth + 1) bar.classList.add("code-terminal-bar--stacked");
}
if (window.ResizeObserver && document.querySelector(".code-terminal-bar")) {
  let barW = 0;                                            // its height changes when it stacks: react to width only
  new ResizeObserver((es) => {
    const w = Math.round(es[0].contentRect.width);
    if (w !== barW) { barW = w; codeBarFit(); }
  }).observe(document.querySelector(".code-terminal-bar"));
}

// A typed prompt (a spoken one keeps him until he has read the answer aloud): Ray thinks while the model thinks and
// runs tools, and goes as soon as the answer text starts
function codeRayTyped(replay) {
  return typeof RayFace !== "undefined" && !replay && !code.turnFromVoice && !TTSController.speaking &&
    !!code.state.busy && TTSController.isThinkAllOn();
}

function codeEvent(ev, replay) {
  if (!replay && modelUnloaded &&
      (ev.type === "thinking" || ev.type === "tool_call" || (ev.type === "text" && ev.text && ev.text.trim()))) {
    modelUnloaded = false;
    modelLoading = false;
    if (typeof RayFace !== "undefined" && TTSController.isOrbOn() && RayFace.state.mode === "sleep") {
      const wantThink = (TTSController.isThinkAllOn() || code.turnFromVoice) && !(ev.type === "text" && !code.turnFromVoice);
      RayFace.wake(wantThink ? "think" : "leave");
    }
  }
  if (codeRayTyped(replay) && !modelUnloaded) {
    if (ev.type === "text" && ev.text && ev.text.trim()) RayFace.leave();
    else if (ev.type === "thinking" || ev.type === "tool_call") RayFace.thinking();   // thinks again after a tool
  }
  // a spoken prompt's reply is read sentence by sentence as it arrives
  if (!replay && code.turnFromVoice && TTSController.willAutoSpeak() && TTSController.isStreamOn()) {
    if (ev.type === "text" && ev.text) codeSpeech().push(ev.text);
    else if (ev.type === "tool_call" && code.speech) code.speech.tool();
  }
  // what the turn is about, so on a long task he works at something that matches it (a blueprint, calipers, maths…)
  if (!replay && typeof RayFace !== "undefined") {
    if (ev.type === "user") RayFace.taskStart(ev.text);
    else if (ev.type === "tool_call") RayFace.taskTool(ev.name, ev.args);
    else if (ev.type === "tool_result" && /^(Error|Denied|SECURITY ERROR|SYNTAX ERROR)/.test(ev.text || "")) RayFace.taskError();
  }
  switch (ev.type) {
    case "thinking": {
      const c = codeAssistant();
      if (ev.block != null && c.el.dataset.block == null) {
        c.el.dataset.block = ev.block;
        c.el.querySelector(".cs-think").open = !codeThinkClosed.has(ev.block);
      }
      c.thinking += ev.text;
      codeQueueRender();
      break;
    }
    case "text": codeAssistant().text += ev.text; codeQueueRender(); break;
    case "user":
      codeEnd();
      if (!replay && ev.voice != null) {
        // Only auto-speak if the prompt originated from this browser client (not an external device like the Android app or CLI)
        const isOwnPrompt = code.client ? ev.origin === codeOrigin() : ev.origin !== "ray-android";
        code.turnFromVoice = Boolean(ev.voice) && isOwnPrompt;
        codeSpeechEnd();
        if (code.turnFromVoice && TTSController.willAutoSpeak() && TTSController.orb() && typeof RayFace !== "undefined") {
          if (modelUnloaded) { modelLoading = true; setPill("reading", "Loading model…"); }
          else RayFace.thinking();
        }
      }
      {
        const prompt = ev.seq != null && ev.text && !/^[\/!]/.test(ev.text);   // a prompt: it can be gone back to
        const card = codeCard("code-mobile-card--user", `<div class="code-mobile-card-body">${esc(ev.text)}</div>` + (prompt ? `
          <div class="code-card-actions cs-prompt-actions">
            <button type="button" class="st-btn st-btn--icon st-btn--sm code-card-action" data-prompt-edit title="Edit this prompt and run it again" aria-label="Edit this prompt">✎</button>
            <button type="button" class="st-btn st-btn--icon st-btn--sm code-card-action" data-prompt-rewind title="Rewind to before this prompt" aria-label="Rewind to before this prompt">↶</button>
            <button type="button" class="st-btn st-btn--icon st-btn--sm code-card-action" data-prompt-branch title="Branch: keep the whole conversation in Sessions, go on from before this prompt" aria-label="Branch from before this prompt">⑂</button>
          </div>` : ""));
        if (prompt) { card.dataset.seq = ev.seq; card.dataset.prompt = ev.text; }
      }
      if (!replay && ev.origin && ev.origin === codeOrigin()) codeScroll(true);   // #4014: what you sent is shown, even scrolled up
      break;
    case "tool_call": {
      codeEnd();
      const args = Object.entries(ev.args || {}).map(([k, v]) => `${k}=${String(v).slice(0, 60)}`).join(", ");
      const el = codeCard("cs-tool", `<details><summary><span class="cs-tool-name">◆ ${esc(ev.name)}</span>
        <span class="cs-tool-args">${esc(args)}</span></summary><pre class="cs-tool-result">…</pre></details>`);
      el.dataset.callId = ev.id || "";
      break;
    }
    case "tool_result": {
      const cards = codeFeed().querySelectorAll(".cs-tool");
      const el = [...cards].reverse().find((c) => c.dataset.callId === (ev.id || "")) || cards[cards.length - 1];
      if (el) {
        el.querySelector(".cs-tool-result").textContent = ev.text + (ev.truncated ? "\n…" : "");
        if (/^(Error|Denied|SECURITY ERROR|SYNTAX ERROR)/.test(ev.text)) el.classList.add("cs-tool--err");
      }
      break;
    }
    case "output":
      codeEnd();
      codeCard("code-mobile-card--assistant", `<div class="code-mobile-card-header"><span class="role-tag">${esc(ev.title || "")}</span></div>
        <div class="code-mobile-card-body">${esc(ev.text || "")}</div>
        <div class="code-card-actions">
          <button type="button" class="st-btn st-btn--icon st-btn--sm code-card-action" data-code-copy title="Copy output" aria-label="Copy output">${icon("copy")}</button>
          <button type="button" class="st-btn st-btn--icon st-btn--sm code-card-action" data-code-speak title="Read aloud" aria-label="Read aloud">${icon("volume")}</button>
        </div>`);
      break;
    case "health": codeEnd(); codeCard("code-mobile-card--assistant cs-health", codeHealth(ev.data || {})); break;
    case "notice": codeEnd(); codeCard(`cs-notice cs-notice--${esc(ev.level || "info")}`, esc(ev.text)); break;
    case "progress": codeReading(ev); break;
    case "error":
      codeEnd();
      codeCard("cs-notice cs-notice--error", esc(ev.text));
      codeSpeechEnd();
      code.turnFromVoice = false;
      if (!replay && typeof RayFace !== "undefined" && !TTSController.speaking) RayFace.end(false);
      break;
    case "stats": codeEnd(); codeCard("cs-stats", `${ev.tokens} tokens · ${ev.seconds}s · ${ev.rate} t/s`); break;
    case "approval_request": codeEnd(); codeApprovalCard(ev); break;
    case "approval_resolved": codeResolve(ev.id, ev.ok); break;
    case "cleared":
      codeFeed().innerHTML = "";
      codeEnd();
      code.turnFromVoice = false;
      if (!replay) { codeThinkClosed.clear(); codeSaveThinkState(); }   // a live /clear, not one in the history
      break;
    case "turn_end":
      codeEnd();
      codeReading(null);
      codeOnTurnEnd();
      break;
    case "state": codeSetState(ev); break;
    case "restored": codeRestored(ev); break;
    case "rewound":                                  // the prompt you went back from, back in your input box
      if (!replay && ev.origin === codeOrigin() && ev.cmd !== "/edit" && $("code-mobile-input")) {
        const ta = $("code-mobile-input");
        ta.value = ev.text || "";
        ta.dispatchEvent(new Event("input"));
        ta.focus();
      }
      break;
  }
}

// /resume: the saved conversation replaces the feed, drawn like the history on attach
function codeRestored(ev) {
  code.replaying = true;
  code.turnFromVoice = false;
  codeFeed().innerHTML = "";
  codeEnd();
  code.approvals = {};
  codeThinkClosed.clear(); codeSaveThinkState();
  for (const e of ev.events || []) codeEvent(e, true);
  codeRenderCur();
  codeScroll(true);
  code.replaying = false;
  if ($("sessions-drawer")?.dataset.open === "true") sessionsLoad();
}

// what this page's prompts are marked with: the session's id for it, and inside the Ray Android app "ray-android-app-"
// first, so Ray's phone tools come on for them as for the voice drawer's (dl_mcp origins: "ray-android")
function codeOrigin() {
  if (!code.client) return "";
  return (window.RayAndroid ? "ray-android-app-" : "") + code.client;
}

function codeHello(h) {
  code.replaying = true;
  code.turnFromVoice = false;
  code.client = h.client || "";
  codeFeed().innerHTML = "";
  codeEnd();
  code.approvals = {};
  const events = h.events || [];
  if (!events.length) {
    codeFeed().innerHTML = `<div class="code-mobile-welcome"><div class="code-mobile-welcome-icon">✦</div>
      <div class="code-mobile-welcome-title">CLI session</div>
      <div class="code-mobile-welcome-sub">Ask for a change, or <b>/plan</b> one first. The terminal joins this same session with <code>dl_cli.py --attach</code>.</div></div>`;
  }
  for (const ev of events) codeEvent(ev, true);
  for (const p of (h.state || {}).pending || []) if (!code.approvals[p.id]) codeApprovalCard(p);
  codeRenderCur();
  codeSetState(h.state);
  codeScroll(true);
  code.replaying = false;
}

async function codeConnect() {
  if (code.conn) return;
  const ctl = new AbortController();
  code.conn = ctl;
  code.stale = false;
  let dog = null;
  try {
    const r = await fetch(`api/code/session/events?session=${CODE_SESSION}`, { headers: headers(), signal: ctl.signal });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.error?.message || `HTTP ${r.status}`);
    }
    code.retry = 0;
    code.lastData = Date.now();
    // A stream can die without an error (the phone slept, Wi-Fi or the tunnel dropped): the page then showed nothing
    // more - Clear and Stop seemed to do nothing until a tab switch reconnected.  The server pings every 15 s, so 40 s
    // of silence is a dead stream; an op (Clear, Stop, a prompt) that brought no event in 5 s is one too.
    dog = setInterval(() => {
      const now = Date.now();
      if (now - code.lastData > 40000 || (code.opAt > code.lastData && now - code.opAt > 5000)) {
        code.stale = true;
        ctl.abort();
      }
    }, 2000);
    const reader = r.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      code.lastData = Date.now();
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const block = buf.slice(0, i);
        buf = buf.slice(i + 2);
        const data = block.split("\n").filter((l) => l.startsWith("data: ")).map((l) => l.slice(6)).join("\n");
        if (!data) continue;
        let ev;
        try { ev = JSON.parse(data); } catch (e) { continue; }
        if (ev.type === "hello") codeHello(ev); else codeEvent(ev, false);
      }
    }
  } catch (e) {
    if (e.name !== "AbortError" && code.retry === 0) toast("warn", "CLI session", e.message || String(e), 5000);
  } finally {
    if (dog) clearInterval(dog);
    code.conn = null;
  }
  if (shown("code") && code.stale) {                       // a dead stream: reconnect now, the hello redraws the feed
    code.stale = false;
    code.opAt = 0;
    setTimeout(codeConnect, 0);
  } else if (shown("code") && !ctl.signal.aborted) {      // reconnect: the daemon or the tunnel went away
    code.retry = Math.min(code.retry + 1, 6);
    setTimeout(codeConnect, 500 * 2 ** code.retry);
  }
}

document.addEventListener("visibilitychange", () => {     // back to the page after a while: check the stream first
  if (!document.hidden && shown("code") && code.conn && Date.now() - (code.lastData || 0) > 20000) {
    code.stale = true;
    code.conn.abort();
  }
});

codeFeed()?.addEventListener("toggle", (e) => {
  const d = e.target;
  if (d.tagName !== "DETAILS" || !d.classList.contains("cs-think")) return;
  const block = Number(d.closest(".cs-reply")?.dataset.block);
  if (Number.isNaN(block)) return;
  if (d.open) codeThinkClosed.delete(block); else codeThinkClosed.add(block);
  codeSaveThinkState();
}, true);

function codeDisconnect() { if (code.conn) code.conn.abort(); code.conn = null; }

async function codeOp(op, extra = {}) {
  if (op !== "export" && op !== "archives") code.opAt = Date.now();   // the watchdog expects an event back (codeConnect)
  try {
    const r = await fetch("api/code/session", {
      method: "POST", headers: headers(true),
      body: JSON.stringify({ op, session: CODE_SESSION, origin: codeOrigin(), ...extra }),
    });
    const res = await r.json().catch(() => ({}));
    if (!r.ok || res.type === "error") throw new Error(res.error?.message || res.text || `HTTP ${r.status}`);
    return res;
  } catch (e) {
    toast("error", "CLI session", e.message || String(e));
    return null;
  }
}

async function codeSend(text) {
  if (typeof STTController !== "undefined") {
    STTController.cancelAutoSendTimer();
  }
  const ta = $("code-mobile-input");
  text = (text ?? (ta ? ta.value : "")).trim();
  if (!text) return;

  if (typeof TTSController !== "undefined" && TTSController.speaking) {
    TTSController.stop();
  }

  let fromVoice = false;
  if (STTController.lastInputWasVoice && STTController.lastTranscribedText) {
    const spokenLower = STTController.lastTranscribedText.toLowerCase();
    const textLower = text.toLowerCase();
    if (textLower.includes(spokenLower) || spokenLower.includes(textLower)) {
      fromVoice = true;
    }
  }
  STTController.lastInputWasVoice = false;
  STTController.lastTranscribedText = "";
  if (!fromVoice && typeof TTSController !== "undefined" && TTSController.isSpeakToggleOn() && !/^[\/!]/.test(text)) {
    fromVoice = true;
  }
  if (!code.state.busy) {
    code.turnFromVoice = fromVoice;
    codeSpeechEnd();                               // a reading still open from the last turn
  }

  if (text === "/speak") {
    if (ta && ta.value.trim() === text) { ta.value = ""; ta.style.height = "auto"; }
    const cards = codeFeed() ? codeFeed().querySelectorAll(".code-mobile-card--assistant") : [];
    if (cards.length) {
      const lastCard = cards[cards.length - 1];
      const textEl = lastCard.querySelector(".cs-text") || lastCard.querySelector(".code-mobile-card-body");
      const sp = lastCard.querySelector("[data-code-speak]");
      if (textEl) TTSController.speakText(textEl.innerText || textEl.textContent, sp);
    } else {
      toast("info", "No messages yet", "There is no assistant reply to speak.");
    }
    return;
  }
  // spoken prompt: answered in plain speech (voice: true); thinking level is selected automatically (/effort auto)
  const turn = fromVoice ? { text, voice: true } : { text };
  const res = await codeOp("input", turn);
  if (res) {
    if (ta && ta.value.trim() === text) { ta.value = ""; ta.style.height = "auto"; }
    // the answer will be read aloud: Ray thinks, paw on his chin, until then (or waits curled up while weights load)
    if (!res.queued && fromVoice && TTSController.willAutoSpeak() && TTSController.orb()) {
      if (modelUnloaded) { modelLoading = true; setPill("reading", "Loading model…"); }
      else RayFace.thinking();
    }
  }
}

function openCodeSession() { setScaffoldUI(); codeConnect(); }

function setScaffoldUI() {
  if ($("code-scaffold-title")) $("code-scaffold-title").textContent = "CLI";
}

if ($("code-restart-btn")) {
  $("code-restart-btn").onclick = () => codeSend("/new");     // the current conversation goes to Sessions first
}
if ($("code-stop-btn")) {
  $("code-stop-btn").onclick = () => {
    if (typeof TTSController !== "undefined") TTSController.stop();
    if (typeof RayFace !== "undefined") RayFace.end(false);
    code.turnFromVoice = false;
    codeOp("interrupt");
  };
}
if ($("code-speak-btn")) {
  $("code-speak-btn").onclick = () => {
    const next = !TTSController.isSpeakToggleOn();
    TTSController.setSpeakToggle(next);
    toast("info", `Speak mode ${next ? "enabled" : "disabled"}`, next ? "Ray will read replies aloud automatically." : "Replies will be silent. Tap speaker icon on any message to listen.", 2500);
  };
}
if ($("code-export-btn")) {
  $("code-export-btn").onclick = async () => {
    const res = await codeOp("export");
    if (!res) return;
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([res.markdown || ""], { type: "text/markdown" }));
    a.download = res.filename || "dl-ai-code-chat.md";
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
    toast("success", "Chat saved", a.download);
  };
}
// ------------------------------------------------------------------ saved sessions (dl_sessiond: /sessions)
// /clear and New keep the conversation they end; this drawer lists them, searches their titles and messages, and
// resumes, renames or deletes one. Resume goes through the session like the typed /resume, so every client follows.
let sessionsTimer = null;
function openSessions(open) {
  const d = $("sessions-drawer");
  if (!d) return;
  if (!open && d.contains(document.activeElement)) {        // focus leaves before the drawer is hidden from AT
    document.activeElement.blur();
    try { ($("code-mobile-input") || $("code-sessions-btn")).focus(); } catch (_) {}
  }
  d.dataset.open = String(open);
  d.toggleAttribute("inert", !open);
  d.inert = !open;
  if (open) { d.removeAttribute("aria-hidden"); sessionsLoad(); setTimeout(() => $("sessions-search")?.focus(), 50); }
  else d.setAttribute("aria-hidden", "true");
  $("scrim").hidden = !open;
}
async function sessionsLoad() {
  const q = ($("sessions-search")?.value || "").trim();
  const res = await codeOp("archives", { query: q });
  if (!res) return;
  const cur = res.current || {};
  $("sessions-current").innerHTML = `<div class="sess-item sess-item--current">
      <div class="sess-main"><div class="sess-title">${esc(cur.title || "(nothing asked yet)")}</div>
        <div class="sess-meta">Now open${cur.id ? " · resumed" : ""}</div></div>
      <div class="sess-actions"><button type="button" class="st-btn st-btn--icon st-btn--sm" data-sess-rename-current title="Rename this conversation" aria-label="Rename this conversation">✎</button></div></div>`;
  const items = res.items || [];
  $("sessions-list").innerHTML = items.length ? items.map((m) => {
    const when = m.updated ? new Date(m.updated * 1000).toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) : "";
    const ws = (m.workspace || "").split("/").slice(-2).join("/");
    return `<div class="sess-item" data-sess-id="${esc(m.id)}">
      <button type="button" class="sess-main" data-sess-resume title="Resume this conversation">
        <span class="sess-title">${m.n}. ${esc(m.title || "(untitled)")}</span>
        <span class="sess-meta">${m.turns || 0} prompts · ${esc(when)} · ${esc(ws)}</span>
        ${m.snippet ? `<span class="sess-snippet">${esc(m.snippet)}</span>` : ""}</button>
      <div class="sess-actions">
        <button type="button" class="st-btn st-btn--icon st-btn--sm" data-sess-rename title="Rename" aria-label="Rename">✎</button>
        <button type="button" class="st-btn st-btn--icon st-btn--sm" data-sess-delete title="Delete" aria-label="Delete">${icon("trash")}</button>
      </div></div>`;
  }).join("") : `<p class="muted small">${q ? "Nothing matches." : "No saved conversations yet. New (or /clear) keeps the current one here."}</p>`;
}
if ($("sessions-drawer")) {
  $("code-sessions-btn").onclick = () => openSessions(true);
  $("sessions-close").onclick = () => openSessions(false);
  $("scrim").addEventListener("click", () => openSessions(false));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && $("sessions-drawer").dataset.open === "true") openSessions(false); });
  $("sessions-search").addEventListener("input", () => { clearTimeout(sessionsTimer); sessionsTimer = setTimeout(sessionsLoad, 250); });
  $("sessions-new").onclick = () => { codeSend("/new"); openSessions(false); };
  $("sessions-drawer").addEventListener("click", async (e) => {
    const item = e.target.closest("[data-sess-id]");
    if (e.target.closest("[data-sess-rename-current]")) {
      const t = prompt("Name this conversation:", code.state.title || "");
      if (t && t.trim()) { await codeSend(`/rename ${t.trim()}`); setTimeout(sessionsLoad, 400); }
      return;
    }
    if (!item) return;
    const id = item.dataset.sessId, title = item.querySelector(".sess-title")?.textContent.replace(/^\d+\.\s*/, "") || "";
    if (e.target.closest("[data-sess-resume]")) {
      if (code.state.busy) { toast("warn", "Sessions", "The session is working: stop it or wait, then resume."); return; }
      codeSend(`/resume ${id}`);
      openSessions(false);
    } else if (e.target.closest("[data-sess-rename]")) {
      const t = prompt("Rename this saved conversation:", title);
      if (t && t.trim() && await codeOp("archive_rename", { id, title: t.trim() })) sessionsLoad();
    } else if (e.target.closest("[data-sess-delete]")) {
      if (confirm(`Delete "${title}" from the saved list?`) && await codeOp("archive_delete", { id })) sessionsLoad();
    }
  });
}
if ($("code-fullscreen-btn")) {
  $("code-fullscreen-btn").onclick = () => document.querySelector(".code-terminal-wrap")?.classList.toggle("code-terminal--fullscreen");
}
if (codeFeed()) {
  codeFeed().addEventListener("click", (e) => {
    const sp = e.target.closest("[data-code-speak]");
    if (sp) {
      const card = sp.closest(".code-mobile-card");
      const textEl = card.querySelector(".cs-text") || card.querySelector(".code-mobile-card-body");
      if (textEl) TTSController.speakText(textEl.innerText || textEl.textContent, sp);
      return;
    }
    const pa = e.target.closest("[data-prompt-edit],[data-prompt-rewind],[data-prompt-branch],[data-prompt-send],[data-prompt-send-branch],[data-prompt-cancel]");
    if (pa) { codePromptAction(pa); return; }
    const cp = e.target.closest("[data-code-copy]");
    if (cp) {
      const card = cp.closest(".code-mobile-card");
      const textEl = card.querySelector(".cs-text") || card.querySelector(".code-mobile-card-body");
      if (textEl) copyText(textEl.innerText || textEl.textContent, cp);
      return;
    }
  });
}
// A past prompt: edit it in place and run it again (/edit), rewind to before it (/rewind), or branch from before it
// (/branch: the whole conversation stays in Sessions). The daemon cuts the conversation and every client redraws it.
function codePromptAction(btn) {
  const card = btn.closest(".code-mobile-card--user");
  if (!card) return;
  const ref = `@${card.dataset.seq}`, body = card.querySelector(".code-mobile-card-body");
  if (btn.matches("[data-prompt-cancel]")) { body.textContent = card.dataset.prompt; card.classList.remove("cs-editing"); return; }
  if (code.state.busy) { toast("warn", "CLI session", "The session is working: stop it or wait first."); return; }
  if (btn.matches("[data-prompt-edit]")) {
    if (card.classList.contains("cs-editing")) return;
    card.classList.add("cs-editing");
    body.innerHTML = `<textarea class="cs-edit-input" rows="3" aria-label="Edited prompt"></textarea>
      <div class="cs-edit-actions">
        <button type="button" class="st-btn st-btn--primary st-btn--sm" data-prompt-send title="Replace this prompt and run it; what came after it is removed">Send</button>
        <button type="button" class="st-btn st-btn--secondary st-btn--sm" data-prompt-send-branch title="Keep the whole conversation in Sessions and run the edited prompt in a branch">Send as branch</button>
        <button type="button" class="st-btn st-btn--secondary st-btn--sm" data-prompt-cancel>Cancel</button></div>`;
    const ta = body.querySelector("textarea");
    ta.value = card.dataset.prompt;
    ta.style.height = Math.min(ta.scrollHeight + 4, 240) + "px";
    ta.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); body.querySelector("[data-prompt-send]").click(); }
      if (e.key === "Escape") { e.stopPropagation(); body.querySelector("[data-prompt-cancel]").click(); }
    });
    ta.focus();
    return;
  }
  if (btn.matches("[data-prompt-send],[data-prompt-send-branch]")) {
    const text = (body.querySelector("textarea")?.value || "").trim();
    if (!text) return;
    codeSend(`${btn.matches("[data-prompt-send]") ? "/edit" : "/branch"} ${ref} ${text}`);
    return;
  }
  if (btn.matches("[data-prompt-rewind]")) {
    if (confirm("Rewind to before this prompt? It and everything after it are removed (Branch keeps them).")) codeSend(`/rewind ${ref}`);
    return;
  }
  if (btn.matches("[data-prompt-branch]")) codeSend(`/branch ${ref}`);
}
if ($("code-mobile-send-btn")) $("code-mobile-send-btn").onclick = () => codeSend();
if ($("code-mobile-input")) {
  $("code-mobile-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); codeSend(); }
  });
  $("code-mobile-input").addEventListener("input", function (e) {
    this.style.height = "auto";
    this.style.height = Math.min(this.scrollHeight, 160) + "px";
    if (e.isTrusted && !STTController.isRecording) {
      if (!this.value.trim()) {
        STTController.lastInputWasVoice = false;
        STTController.lastTranscribedText = "";
      }
    }
  });
  // Screenshot and file pasting directly into chat/code input (#3748, #3838)
  $("code-mobile-input").addEventListener("paste", async (e) => {
    const dt = e.clipboardData;
    if (!dt) return;
    const files = [];
    for (const f of Array.from(dt.files || [])) {
      if (f.type.startsWith("image/") || /\.pdf$/i.test(f.name)) files.push(f);
    }
    // Screenshots on clipboard (Win+Shift+S / Spectacle) often arrive in items rather than files
    if (!files.some(f => f.type.startsWith("image/"))) {
      for (const item of Array.from(dt.items || [])) {
        if (item.kind === "file" && item.type.startsWith("image/")) {
          const file = item.getAsFile();
          if (file) {
            const ext = file.type.split("/")[1]?.replace("jpeg", "jpg").replace(/[+].*/, "") || "png";
            const now = new Date();
            const pad = (n) => String(n).padStart(2, "0");
            const stamp = `${now.getFullYear()}${pad(now.getMonth()+1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
            const name = `pasted-image-${stamp}${files.length ? `-${files.length + 1}` : ""}.${ext}`;
            files.push(new File([file], name, { type: file.type }));
          }
        }
      }
    }
    if (files.length) {
      e.preventDefault();
      const stored = await uploadFilesToWorkspace(files, "uploads/");
      const input = $("code-mobile-input");
      const refs = stored.map(p => `@${p}`).join(" ");
      input.value = input.value ? `${input.value.trimEnd()} ${refs} ` : `${refs} `;
      input.focus();
      input.dispatchEvent(new Event("input"));
      toast("success", "File attached", files.map(f => f.name).join(", "), 3000);
    }
  });
}
document.querySelectorAll(".code-mobile-chip").forEach((chip) => {
  chip.onclick = () => {
    const cmd = chip.dataset.cmd;
    if ("run" in chip.dataset) { codeSend(cmd); return; }
    const input = $("code-mobile-input");
    input.value = cmd + " ";
    input.focus();
  };
});
document.addEventListener("visibilitychange", () => {     // phones suspend background tabs: reconnect on return
  if (document.visibilityState === "visible" && shown("code") && !code.conn) codeConnect();
});

