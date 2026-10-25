#!/usr/bin/env python3
"""dl_sessiond.py - D.L. AI shared CLI sessions: one agent session, driven from any number of clients at once.

The agent (dl_cli's loop, tools and prompts) runs here, not in a terminal.  Clients attach over a Unix socket and
all see the same live event stream: the terminal (`dl_cli.py --attach`) and the web app's Code tab (bridged by
serve/server.py at /api/code/session).  Start a task on the phone, continue it in Konsole, and back.

Protocol: JSON lines on $XDG_RUNTIME_DIR/dl-ai/sessiond.sock (mode 600).
  {"op": "attach", "session": "dl-ai-code"}       -> {"type": "hello", "state": {...}, "events": [...]}, then live
  {"op": "input", "session": ..., "text": "...", "effort": "none"}  a prompt, a /command or !shell; effort (optional):
                                                  this turn's thinking level, over the session's /effort; voice: true adds the spoken-answer note
  {"op": "approve" | "deny", "session": ..., "id": "..."}
  {"op": "interrupt", "session": ...}
  {"op": "export", "session": ...}                -> {"type": "export", "markdown": ..., "filename": ...}
An attached connection may send further ops; any other connection gets one {"type": "ok"} (or an error) reply.

Sessions persist in ~/.local/state/dl-ai/sessions/<name>.json (history, workspace, mode, recent events).
"""
from __future__ import annotations

import datetime
import json
import os
import queue
import re
import signal
import socket
import socketserver
import sys
import threading
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dl_cli as cli  # noqa: E402
import dl_effort  # noqa: E402
import dl_mcp  # noqa: E402
import dl_schedule  # noqa: E402
from dl_auditing import format_health_card, get_system_health  # noqa: E402

RUNTIME = Path(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}") / "dl-ai"
SOCKET_PATH = RUNTIME / "sessiond.sock"
STATE_DIR = Path.home() / ".local" / "state" / "dl-ai" / "sessions"
DEFAULT_SESSION = "dl-ai-code"
REPLAY_MAX = 3000                 # events kept for a client that attaches later
# Every event, one JSON line each, in <name>/<date>.jsonl (off with DL_TRANSCRIPT=0). The replay above keeps only
# the last 3,000 and the chat export only what is still in the context: on 2026-10-20 the CONTRA export had 47 of
# its 4,383 messages.  "/save full" renders the transcript since the last /clear.
TRANSCRIPT_DIR = STATE_DIR.parent / "transcripts"
APPROVAL_TIMEOUT = 30 * 60        # an unanswered approval is a "no"
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
NAME_OK = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")

EFFORTS = ("none", "low", "medium", "high")
SESSION_EFFORTS = EFFORTS + ("auto",)
EXECUTE_PLAN = ("Proceed with executing the plan now. Perform the necessary tool calls (edits, writes, tests, "
                "commands) to implement the agreed plan.")
EXECUTE_PLAN_FILE = ("Execute the approved plan in {plan} now, step by step, with the tool calls it needs (edits, "
                     "writes, tests, commands). Keep its \"## Progress\" checklist current: tick each line (\"- [x]\") "
                     "as soon as its own check passes - one line at a time, not when the whole section is done - "
                     "and if you cannot go on, add a \"Blocked: <reason>\" line and say why. "
                     "The task is done when every step is ticked.")


def plain(text: str) -> str:
    return ANSI.sub("", text or "")


_save_lock = threading.Lock()


class Session:
    def __init__(self, name: str, workspace: Path):
        self.name = name
        self.workspace = workspace
        self.mode = "act"
        self.yolo = False
        self.effort: str | None = "auto"          # /effort: this session's thinking level; default auto
        self.last_auto: tuple[str, str] | None = None
        self.messages: list[dict] = [{"role": "system", "content": cli.build_dl_system_prompt(workspace, "act")}]
        self.events: list[dict] = []
        self._open_block: dict | None = None    # the thinking/text block still growing; transcribed once complete
        self.seq = 0
        self.clients: set[queue.Queue] = set()
        self.lock = threading.RLock()
        self.busy = False
        self.cancel = threading.Event()
        self.pending: dict[str, dict] = {}       # approval id -> {"event", "ok", "kind", ...}
        self.plan_offer: str | None = None       # id of an open "Execute this plan?" offer
        self.plan_file: str | None = None        # the approved plan (PLAN.md) the done check holds the agent to
        self._plan_mtime: int | None = None      # the plan's mtime when a state was last sent for it
        # MCP servers, on while a request needs them; "code": Google (Gmail) is allowed here, not in the REPL
        self.mcp = dl_mcp.McpRegistry(surface="code", notify=lambda t, level="info": self.notice(f"MCP {t}", level))
        self.mcp.on_change = self.emit_state

    # ---------------------------------------------------------------- events
    def emit(self, ev: dict) -> None:
        with self.lock:
            self.seq += 1
            ev = {**ev, "seq": self.seq, "ts": round(time.time(), 3)}
            last = self.events[-1] if self.events else None
            merge = bool(last and ev["type"] in ("thinking", "text") and last["type"] == ev["type"]
                         and last is self._open_block)          # never grow a block already transcribed
            if ev["type"] in ("thinking", "text"):             # a stable id for the block, live and in replay
                ev["block"] = last.get("block", last["seq"]) if merge else self.seq
            if merge:
                last["text"] += ev["text"]                     # replay keeps one block, live clients get deltas
                last["seq"] = ev["seq"]
            else:
                if self._open_block is not None:               # the block before this event is complete
                    self._transcribe(self._open_block)
                    self._open_block = None
                stored = dict(ev)
                self.events.append(stored)
                if ev["type"] in ("thinking", "text"):
                    self._open_block = stored
                else:
                    self._transcribe(stored)
                if len(self.events) > REPLAY_MAX:
                    del self.events[:len(self.events) - REPLAY_MAX]
            for q in list(self.clients):
                q.put(ev)
        if ev["type"] == "tool_result":
            self._plan_changed()

    def _transcribe(self, ev: dict) -> None:
        if os.environ.get("DL_TRANSCRIPT") != "1":       # main() turns it on; tests that import this stay off
            return
        try:
            folder = TRANSCRIPT_DIR / self.name
            folder.mkdir(parents=True, exist_ok=True, mode=0o700)
            day = time.strftime("%Y-%m-%d", time.localtime(ev.get("ts") or time.time()))
            fd = os.open(folder / f"{day}.jsonl", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(fd, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(ev, ensure_ascii=False) + "\n")
        except OSError:
            pass                                 # a full disk must not stop the session

    def _plan_changed(self) -> None:
        """A tool may have ticked the plan: send a fresh state when PLAN.md changed, so the Code tab's plan chip
        follows a long YOLO request instead of showing the count from its start (2026-10-20: 15/99 shown at 27/99)."""
        pf = self.plan_file
        if not pf:
            return
        try:
            mtime = os.stat(pf).st_mtime_ns
        except OSError:
            return
        if mtime != self._plan_mtime:
            self._plan_mtime = mtime
            self.emit_state()

    def state(self) -> dict:
        return {"type": "state", "session": self.name, "workspace": str(self.workspace), "mode": self.mode,
                "settings": cli.chat_settings_summary(), "effort": self.effort, "yolo": self.yolo, "busy": self.busy,
                "wiki": str(cli.resolve_wiki_root(self.workspace) or ""),
                "mcp": [m for m in self.mcp.status() if m["on"]], "plan": self.plan_summary(),
                "pending": [{"id": k, "kind": v["kind"], "summary": v["summary"], "reason": v["reason"]}
                            for k, v in self.pending.items()]}

    def plan_summary(self) -> dict | None:
        """For the web Code tab's plan chip: the active plan's file and its Progress counts."""
        if not self.plan_file or not Path(self.plan_file).is_file():
            return None
        _, open_items, done_items, blocked = cli.plan_progress(Path(self.plan_file))
        p = Path(self.plan_file)
        return {"file": str(p.relative_to(self.workspace)) if p.is_relative_to(self.workspace) else str(p),
                "done": len(done_items), "open": len(open_items), "blocked": blocked}

    def emit_state(self) -> None:
        self.emit(self.state())

    def output(self, title: str, text: str, kind: str = "output") -> None:
        self.emit({"type": kind, "title": title, "text": plain(text), "ansi": text})

    def notice(self, text: str, level: str = "info") -> None:
        self.emit({"type": "notice", "level": level, "text": text})

    # ---------------------------------------------------------------- persistence
    def path(self) -> Path:
        return STATE_DIR / f"{self.name}.json"

    def save(self) -> None:
        with self.lock, _save_lock:
            if self._open_block is not None and not self.busy:   # between turns the last block cannot grow
                self._transcribe(self._open_block)
                self._open_block = None
            data = {"name": self.name, "workspace": str(self.workspace), "mode": self.mode, "effort": self.effort,
                    "yolo": self.yolo, "plan_file": self.plan_file,
                    "messages": self.messages, "events": self.events[-REPLAY_MAX:], "seq": self.seq}
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            tmp = self.path().with_suffix(".tmp")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)   # private from the start
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(json.dumps(data, ensure_ascii=False))
            os.chmod(tmp, 0o600)
            tmp.replace(self.path())

    @classmethod
    def load(cls, name: str, default_ws: Path) -> "Session":
        p = STATE_DIR / f"{name}.json"
        try:
            raw = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return cls(name, default_ws)
        try:
            data = json.loads(raw)
        except ValueError:
            data = None
        if not (isinstance(data, dict) and isinstance(data.get("workspace") or "", str)
                and isinstance(data.get("messages") or [], list) and isinstance(data.get("events") or [], list)):
            # damaged: keep a private copy (the next save would replace it), start the session fresh
            if raw.strip():
                try:
                    keep = p.with_name(f"{p.name}.unreadable-{time.strftime('%Y%m%d-%H%M%S')}")
                    fd = os.open(keep, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                    with os.fdopen(fd, "w", encoding="utf-8") as fh:
                        fh.write(raw)
                except OSError:
                    pass
            return cls(name, default_ws)
        ws = Path(data.get("workspace") or default_ws)
        s = cls(name, ws if ws.is_dir() else default_ws)
        s.mode = data.get("mode") if data.get("mode") in ("act", "plan") else "act"
        s.effort = data.get("effort") if data.get("effort") in SESSION_EFFORTS else "auto"
        pf = data.get("plan_file")
        s.plan_file = pf if isinstance(pf, str) and Path(pf).is_file() else None
        s.yolo = data.get("yolo") is True             # YOLO stays on until it is turned off, also after restarts
        # what the model can be sent again: an assistant turn as saved (it may hold only tool calls), anything else
        # only with its text
        msgs = [m for m in data.get("messages") or [] if isinstance(m, dict) and (
            m.get("role") == "assistant" or (m.get("role") in ("system", "user", "tool")
                                             and isinstance(m.get("content"), (str, list))))]   # list: parts, e.g. images
        s.messages = msgs or s.messages
        system = {"role": "system", "content": cli.build_dl_system_prompt(s.workspace, s.mode, s.plan_file)}
        if s.messages[0].get("role") == "system":
            s.messages[0] = system
        else:
            s.messages.insert(0, system)
        s.events = [e for e in data.get("events") or [] if isinstance(e, dict)]
        seq = data.get("seq")
        used = [e["seq"] for e in s.events if type(e.get("seq")) is int]
        # never below a number already shown: the web app keys thinking blocks by it
        s.seq = max([seq if type(seq) is int else 0, len(s.events), *used])
        return s

    # ---------------------------------------------------------------- approvals
    def approve(self, kind: str, summary: str, reason: str, cancel: threading.Event | None = None) -> bool:
        """The dl_cli approver: ask every attached client, wait for the first answer.  `cancel`: what stops the
        wait (default this session's; a scheduled job passes its own, so an old interrupt here cannot deny it)."""
        cancel = self.cancel if cancel is None else cancel
        aid = uuid.uuid4().hex[:10]
        ev = threading.Event()
        with self.lock:
            self.pending[aid] = {"event": ev, "ok": False, "kind": kind, "summary": summary, "reason": reason}
        self.emit({"type": "approval_request", "id": aid, "kind": kind, "summary": summary, "reason": reason})
        deadline = time.time() + APPROVAL_TIMEOUT
        while not ev.wait(0.5):
            if cancel.is_set() or time.time() > deadline:
                break
        with self.lock:
            ok = self.pending.pop(aid, {}).get("ok", False)
        self.emit({"type": "approval_resolved", "id": aid, "ok": ok})
        return ok

    def answer(self, aid: str, ok: bool) -> bool:
        if aid and aid == self.plan_offer:
            self.plan_offer = None
            self.emit({"type": "approval_resolved", "id": aid, "ok": ok})
            if ok:
                self.submit("/act")
            return True
        with self.lock:
            p = self.pending.get(aid)
            if not p:
                return False
            p["ok"] = ok
            p["event"].set()
        return True

    def interrupt(self) -> None:
        if self.busy:
            self.cancel.set()
            with self.lock:
                for p in self.pending.values():
                    p["event"].set()

    # ---------------------------------------------------------------- input
    def submit(self, text: str, origin: str = "", effort: str | None = None, voice: bool = False) -> None:
        text = (text or "").strip()
        if not text:
            return
        with self.lock:
            if self.busy:
                self.notice("The session is working - wait for it, or interrupt it first.", "warn")
                return
            self.busy = True
            self.cancel.clear()
            if self.plan_offer:                       # a new prompt replaces the open "Execute this plan?"
                self.emit({"type": "approval_resolved", "id": self.plan_offer, "ok": False})
                self.plan_offer = None
        threading.Thread(target=self._run, args=(text, origin, effort, voice), daemon=True).start()

    def _run(self, text: str, origin: str, effort: str | None = None, voice: bool = False) -> None:
        self.emit({"type": "user", "text": text, "origin": origin})
        self.emit_state()
        try:
            prompt = self._command(text)
            if prompt is not None:
                self._agent(prompt, effort, voice)
        except Exception as e:                        # a turn's failure never takes the daemon down
            self.emit({"type": "error", "text": str(e)})
            if self.messages and self.messages[-1].get("role") == "user":
                self.messages.pop()
        finally:
            with self.lock:
                self.busy = False
            try:
                self.save()
            except OSError as e:
                self.emit({"type": "error", "text": f"could not save the session: {e}"})
            self.emit({"type": "turn_end"})
            self.emit_state()

    def _system(self) -> None:
        self.messages[0] = {"role": "system", "content": cli.build_dl_system_prompt(self.workspace, self.mode,
                                                                                   self.plan_file)}

    def _transcript(self, prompt: str, out: str) -> None:
        self.messages.append({"role": "user", "content": prompt})
        self.messages.append({"role": "assistant", "content": plain(out)})

    def _agent(self, prompt: str, effort: str | None = None, voice: bool = False) -> None:
        # what built-ins (schedule, deepl, proton) need to know about this turn; the user asked "now"
        dl_mcp.CALL.ctx = {"workspace": self.workspace, "yolo": self.yolo, "request_time": time.time(),
                           "registry": self.mcp, "job": getattr(self, "job_id", None)}
        turn_effort = effort or self.effort                 # a turn's own level (a spoken prompt: none) wins
        effort_auto = not effort and self.effort == "auto"
        if effort_auto:
            last_reply = next((m.get("content") or "" for m in reversed(self.messages)
                               if m.get("role") == "assistant" and isinstance(m.get("content"), str)), "")
            level, reason = dl_effort.pick(prompt, voice=voice, mode=self.mode, last_reply=last_reply)
            budget = dl_effort.budget_for(level)
            self.last_auto = (level, reason)
            self.notice(f"Auto thinking: {level} ({reason}{f', cap: {budget}' if budget else ''})")
            resolved_effort = level
            resolved_budget = budget
        else:
            resolved_effort = turn_effort
            resolved_budget = 0
        self.messages.append({"role": "user",
                              "content": cli.build_user_message_content(prompt, self.workspace, voice=voice)})
        ctx = {"workspace": self.workspace, "messages": self.messages, "mode": self.mode, "yolo": self.yolo,
               "plan_file": self.plan_file,
               "effort": resolved_effort,
               "effort_auto": effort_auto,
               "reasoning_budget_tokens": resolved_budget,
               "emit": self.emit, "cancel": self.cancel, "approve": self.approve, "mcp": self.mcp, "user_text": prompt,
               "session": self}
        new_ws = cli.execute_agent_loop(messages=self.messages, url=cli.DEFAULT_URL, api_key=cli.DEFAULT_API_KEY,
                                        workspace=self.workspace, mode=self.mode,
                                        session_context=ctx)
        if ctx.get("plan_file") != self.plan_file:          # the done check found it complete
            self.plan_file = ctx.get("plan_file")
            self.emit_state()
        if new_ws != self.workspace:
            self.workspace = new_ws
            self.emit_state()
        if (self.mode == "plan" and not self.cancel.is_set() and self.messages
                and self.messages[-1].get("role") == "assistant"):
            self.plan_offer = uuid.uuid4().hex[:10]
            self.emit({"type": "approval_request", "id": self.plan_offer, "kind": "plan",
                       "summary": "Execute this plan?", "reason": "switches to Act Mode and runs it"})

    def _command(self, text: str) -> str | None:
        """Run a /command or !shell; returns the prompt for the agent, or None when handled here."""
        if text.startswith("!"):
            cmd = text[1:].strip()
            out = cli.dispatch_dl_tool("run_command", {"CommandLine": cmd}, self.workspace, mode="act",
                                       session_context={"yolo": self.yolo, "approve": self.approve})
            self.output(f"$ {cmd}", out)
            return None
        low = text.strip().lower()
        if low in ("/continue", "continue", "keep going", "go on", "proceed"):
            return cli.CONTINUE_PROMPT
        if not text.startswith("/"):
            return text
        cmd, _, arg = text.partition(" ")
        arg = arg.strip()
        if cmd in ("/act", "/execute"):
            saved = cli.save_approved_plan(self.messages, self.workspace) if self.mode == "plan" else None
            if saved:
                self.plan_file = str(saved)
                self.notice(f"Plan saved to {saved.name}; the agent works from it and ticks its Progress checklist.")
            self.mode = "act"
            self._system()
            self.emit_state()
            if arg:
                return arg
            return EXECUTE_PLAN_FILE.format(plan=saved.name) if saved else EXECUTE_PLAN
        if cmd == "/planfile":
            if arg.lower() in ("off", "none", "clear"):
                self.plan_file = None
                self.notice("No active plan: the done check is off for this session.")
            elif arg:
                p = Path(arg).expanduser()
                p = p if p.is_absolute() else (self.workspace / p)
                if not p.is_file():
                    self.notice(f"No such file: {p}", "warn")
                    return None
                self.plan_file = str(p.resolve())
                _, open_items, done_items, _ = cli.plan_progress(p)
                self.notice(f"Active plan: {p.name} ({len(done_items)} done, {len(open_items)} open)."
                            + ("" if open_items or done_items else " It has no Progress checklist yet; the agent "
                               "is asked to add one."))
            else:
                self.notice(f"Active plan: {self.plan_file or 'none'}. /planfile <path> sets it, /planfile off "
                            "clears it.")
            self._system()
            self.emit_state()
            return None
        if cmd == "/plan":
            if not arg and self.mode == "plan":
                self.mode = "act"
                self._system()
                self.notice("Plan Mode off - Act Mode.")
                return None
            self.mode = "plan"
            self._system()
            self.emit_state()
            if not arg:
                self.notice("Plan Mode: read-only research and design. Ask for a plan.")
                return None
            return arg
        if cmd == "/continue":
            return arg or cli.CONTINUE_PROMPT
        if cmd == "/effort":
            if arg in ("", "show"):
                if self.effort == "auto":
                    if getattr(self, "last_auto", None):
                        lev, reas = self.last_auto
                        self.notice(f"Thinking level: auto (last: {lev}, {reas})")
                    else:
                        self.notice("Thinking level: auto (default)")
                else:
                    self.notice(f"Thinking level: {self.effort or 'the Chat settings (' + cli.chat_settings_summary() + ')'}")
                return None
            if arg not in SESSION_EFFORTS and arg != "default":
                self.notice(f"Usage: /effort {'|'.join(SESSION_EFFORTS)}|default", "warn")
                return None
            self.effort = "auto" if arg == "default" else arg
            if self.effort != "auto":
                self.last_auto = None
            self.notice(f"Thinking level for this session: {self.effort or 'the Chat settings'}")
            self.emit_state()
            return None
        if cmd == "/yolo":
            self.yolo = not self.yolo
            self.notice("YOLO on: nothing asks any more, sending email included, until you turn it off "
                        "(also after restarts; jobs scheduled now run without asking too)." if self.yolo
                        else "Approvals back on.", "warn" if self.yolo else "info")
            self.emit_state()
            return None
        if cmd in ("/clear", "/reset"):
            self.plan_file = None
            self.messages = [{"role": "system", "content": cli.build_dl_system_prompt(self.workspace, self.mode)}]
            with self.lock:
                self.events = []
            self.emit({"type": "cleared"})
            self.mcp.close()                     # a new conversation starts with only the default servers
            self.notice(f"Memory reset ({self.mode} mode).")
            self.emit_state()
            return None
        if cmd == "/mcp":
            self.output("/mcp", self.mcp.command(arg))
            return None
        if cmd == "/schedule":
            self.output("/schedule", schedule_command(arg, self.workspace, self.yolo))
            return None
        if cmd == "/think":
            self.notice("/think is gone: the CLI follows the web app's Chat settings "
                        f"({cli.chat_settings_summary()}). Change them under Chat > Settings, or set this "
                        "session's own level with /effort none|low|medium|high|auto.")
            return None
        if cmd == "/cd":
            cand = Path(arg or str(Path.home())).expanduser()
            cand = (self.workspace / cand).resolve() if not cand.is_absolute() else cand.resolve()
            cand.mkdir(parents=True, exist_ok=True)
            if not cand.is_dir():
                self.emit({"type": "error", "text": f"{cand} is not a directory"})
                return None
            self.workspace = cand
            self._system()
            wroot = cli.resolve_wiki_root(cand)
            self.notice(f"Working directory: {cand}" + (f" · wiki {wroot}" if wroot else " · no wiki"))
            return None
        if cmd in ("/status", "/model"):
            out = cli.check_status(cli.DEFAULT_URL, cli.DEFAULT_API_KEY)
            self.output("Strata engine", out)
            self._transcript(text, out)
            return None
        if cmd in ("/health", "/sys"):
            stats = get_system_health(cli.DEFAULT_URL, cli.DEFAULT_API_KEY)
            card = format_health_card(stats)
            self.emit({"type": "health", "data": stats, "ansi": card, "text": plain(card)})
            self._transcript(text, card)
            return None
        if cmd in ("/exa", "/search"):
            if not arg:
                self.notice("Usage: /exa <query>")
                return None
            out = cli.tool_exa_web_search({"query": arg})
            self.output(f"Exa: {arg}", out)
            self._transcript(text, out)
            return None
        if cmd in ("/context7", "/docs"):
            if not arg:
                self.notice("Usage: /context7 <library>")
                return None
            out = cli.tool_context7_resolve({"libraryName": arg})
            self.output(f"Context7: {arg}", out)
            self._transcript(text, out)
            return None
        if cmd in ("/diff", "/audit"):
            out = cli.tool_git_diff_audit({}, self.workspace)
            self.output("Git diff audit", out)
            self._transcript(text, out)
            return None
        if cmd in ("/secrets", "/scan"):
            self.output("Secret scan", cli.tool_scan_secrets({"path": arg} if arg else {}, self.workspace))
            return None
        if cmd == "/test":
            self.output("Tests", cli.tool_smart_test_runner({"files": arg.split()} if arg else {}, self.workspace))
            return None
        if cmd == "/wiki":
            sub, _, q = arg.partition(" ")
            action = {"lint": "lint", "digest": "digest", "env": "env_list"}.get(sub)
            args = {"action": action} if action else {"action": "search", "query": (q if sub == "search" else arg)}
            if not action and not args["query"]:
                args = {"action": "digest"}
            self.output("Local wiki", cli.tool_local_wiki(args, self.workspace, mode=self.mode))
            return None
        if cmd in ("/save", "/export"):
            full = arg.split(" ", 1)[0].lower() == "full"
            arg = arg.split(" ", 1)[1].strip() if full and " " in arg else ("" if full else arg)
            name, md = self.export(full=full)
            out = Path(arg).expanduser() if arg else self.workspace / name
            out = out if out.is_absolute() else self.workspace / out
            out.write_text(md, encoding="utf-8")
            self.notice(f"Saved {out}")
            return None
        if cmd == "/help":
            self.output("Commands", HELP)
            return None
        self.notice(f"Unknown command {cmd} - /help lists them.", "warn")
        return None

    def export(self, full: bool = False) -> tuple[str, str]:
        stamp = datetime.datetime.now().strftime("%Y-%m-%d-%H-%M")
        if full:
            return f"dl-ai-code-chat-{stamp}-full.md", self.transcript_markdown()
        return (f"dl-ai-code-chat-{stamp}.md",
                cli.format_messages_to_markdown(self.messages, workspace=self.workspace))

    def transcript_events(self) -> list[dict]:
        """This session's transcript since its last /clear, oldest first (newest files are read first, so a long
        history before the /clear is not read)."""
        out: list[dict] = []
        for p in sorted((TRANSCRIPT_DIR / self.name).glob("*.jsonl"), reverse=True):
            try:
                lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for line in reversed(lines):
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if ev.get("type") == "cleared":
                    return out[::-1]
                out.append(ev)
        return out[::-1]

    def transcript_markdown(self) -> str:
        """The chat export with everything the transcript has: every message, thinking block, tool call with its
        result (as the Code tab showed it, up to 4,000 chars) and D.L. CLI notice."""
        model = "Qwen3.8-Flash-Next Coder"
        events = self.transcript_events()
        results = {e.get("id"): e for e in events if e.get("type") == "tool_result"}
        out = ["# Strata CLI Chat Export (full transcript)",
               f"- **Date**: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", f"- **Model**: {model}",
               f"- **Workspace**: `{self.workspace}`", f"- **Events**: {len(events):,}", "", "---", ""]
        who = None
        for ev in events:
            kind = ev.get("type")
            stamp = time.strftime("%H:%M:%S", time.localtime(ev.get("ts") or 0))
            if kind == "user":
                out += [f"## You ({stamp})", "", str(ev.get("text") or ""), ""]
                who = "user"
                continue
            if kind not in ("thinking", "text", "tool_call", "notice"):
                continue
            if who != "model":
                out += [f"## {model} ({stamp})", ""]
                who = "model"
            if kind == "thinking":
                out += ["<details><summary>Thinking</summary>", "", str(ev.get("text") or "").strip(), "",
                        "</details>", ""]
            elif kind == "text":
                out += [str(ev.get("text") or "").strip(), ""]
            elif kind == "notice":
                out += [f"> **D.L. CLI ({stamp}):** {ev.get('text') or ''}", ""]
            else:
                r = results.get(ev.get("id")) or {}
                out += [f"<details><summary>Tool {ev.get('name')} ({stamp})</summary>", "", "````json",
                        json.dumps(ev.get("args"), indent=2, ensure_ascii=False), "````", "", "````",
                        str(r.get("text") or ""), "````", *(["(result cut to 4,000 chars)"] if r.get("truncated") else []),
                        "", "</details>", ""]
        return "\n".join(out)


HELP = """Modes
/plan [task]      Plan Mode: read-only research, ends with "Execute this plan?"
/act [task]       Act Mode (executes the agreed plan when given no task; it is saved as PLAN.md); also /execute
/planfile [path]  The plan the agent is held to (ticks its Progress; done check); off clears it
/yolo             Fully autonomous: nothing asks (sending email included) until you turn it off again
/effort [level]   This session's thinking level: none, low, medium, high, auto, or default (the Chat settings)

Tools and jobs
/mcp [on|off N]   On-demand tools: Home Assistant, web search (Exa), Context7, Fetch, DeepL, browser,
                  Proton Mail, Gmail, Drive, Docs, schedule, DeepSeek cloud reasoning, Europe PMC,
                  arXiv preprints, Wikipedia, OSV vulnerabilities, PubChem, IETF RFC, OpenAlex,
                  OpenStreetMap, ClinicalTrials.gov, Open Targets, Reactome, Modern Web, 3D printing
                  (Klipper & Bambu/Prusa filaments), CAD & materials, Game patterns, Croatian & EU laws,
                  live weather, miniature painting & wargaming (3,340+ paints, airbrushing, Warhammer 40k rules/recipes, BGG mechanics),
                  electronics (LCSC/JLCPCB parts, SMD resistor calc, IPC-2152 PCB trace & decoupling), networking & LAN,
                  photography, video & audio (exposure, log profiles, DaVinci Resolve CST, storyboarding, YouTube/Broadcast LUFS, mics),
                  drones & regulations (DJI specs, CCAA & EASA Croatian rules, AMC Portal),
                  Zagreb civic & transit (ZET, BAJS live bikes, 24/7 pharmacies, Poison Control/vet ER, waste, air quality),
                  Croatia live data (HAK roads/borders, DHMZ weather, HNB currency rates, holidays & Sunday shopping, fuel, METAR),
                  SolidCraft 3D CAD (parametric parts, STEP/STL export, GPU rendering into workspace),
                  Ray self-identity & project telemetry (GitHub repo status, commit changelog, host hardware, MCP catalog)
                  (list, turn on/off; they also start when needed)
/schedule ...     Scheduled jobs: /schedule [--email] <when> <task>; list; off|on|run|rm N; stop (the running job)
                  when: 2026-10-16 09:00, tomorrow 07:00, fri 09:00, in 2h, daily 08:00, mon-fri 07:30, every 2h

Workspace
/cd <path>        Change the working directory (the wiki follows it)
/diff             Git diff audit (also /audit)   /secrets [path]  Secret scan (also /scan)
/test [files]     Targeted tests                 /wiki [search|lint|digest]  Local Wiki
!<command>        Run a shell command in the workspace

Session
/status /health   Engine status (also /model), hardware health (also /sys)
/continue         Go on after the agent stopped at its tool-round limit (DL_MAX_TURNS)
/save [file]      Save the chat as Markdown in the workspace (also /export)
/save full [file] The same with the whole run since /clear from the transcript, thinking included
/clear            Reset the conversation (also /reset)
/help             This list

Direct lookups, without the model: /exa <query> (also /search), /context7 <library> (also /docs)"""


def schedule_command(arg: str, workspace: Path, yolo: bool = False) -> str:
    """/schedule: the user typed it, so adding a prompt job needs no approval card."""
    sub, _, rest = arg.strip().partition(" ")
    rest = rest.strip()
    if sub in ("", "list", "ls"):
        running = RUNNING.get("job")
        return dl_schedule.list_text() + (f"\nRunning now: job #{running} (/schedule stop)" if running else "")
    if sub == "stop":
        sess = RUNNING.get("session")
        if not sess:
            return "No scheduled job is running."
        sess.cancel.set()                    # stops its model stream and any approval card it waits on
        return f"Stopping job #{RUNNING.get('job')}."
    if sub in ("off", "on", "run", "rm", "remove", "delete") and rest.lstrip("#").isdigit():
        n = int(rest.lstrip("#"))
        if sub in ("rm", "remove", "delete"):
            return f"Removed #{n}." if dl_schedule.remove(n) else f"No job #{n}."
        if sub == "run":
            with dl_schedule._lock:
                data = dl_schedule.load()
                job = next((j for j in data["jobs"] if isinstance(j, dict) and j.get("id") == n), None)
                if not job:
                    return f"No job #{n}."
                job.update(enabled=True, next=time.time())
                if job["spec"]["kind"] == "once":
                    job["spec"]["at"] = time.time()
                    job["spec"].pop("planned", None)       # a run by hand is not late
                dl_schedule.save(data)
            return f"#{n} runs within {dl_schedule.settings()['tick_s']} s."
        job = dl_schedule.set_enabled(n, sub == "on")
        return dl_schedule.summary(job) if job else f"No job #{n}."
    email = "--email" in arg.split()
    text = " ".join(w for w in arg.split() if w != "--email")
    try:
        job = dl_schedule.add(text, workspace=str(workspace), email_result=email, yolo=yolo)
    except dl_schedule.WhenError as e:
        return f"{e}\nUsage: /schedule [--email] <when> <task> · /schedule list · /schedule off|on|run|rm N"
    return f"Scheduled {dl_schedule.summary(job)}"


def add_late_note(args: dict, planned: float, sent: float) -> dict:
    """A line at the top of a scheduled email that went out late, in the email's own language (DeepL detects it
    and translates the English note; English when DeepL is not reachable)."""
    out = dict(args)
    if out.get("html_file") and not out.get("html"):
        try:
            import dl_proton
            out["html"] = dl_proton._html_of(out)       # the note goes into the HTML itself
            out.pop("html_file")
        except Exception:  # noqa: BLE001 - send_mail reports a missing file itself
            pass
    minutes = round((sent - planned) / 60)
    note = (f"Planned for {dl_schedule.hm(planned)}, sent at {dl_schedule.hm(sent)} "
            f"({minutes} min later than planned).")
    sample = (str(out.get("body") or "") or re.sub(r"<[^>]+>", " ", str(out.get("html") or ""))
              or str(out.get("subject") or ""))
    try:
        import dl_translate
        lang = dl_translate.detect(sample)
        if lang and not lang.upper().startswith("EN"):
            note = dl_translate.translate(note, lang)[0] or note
    except Exception:  # noqa: BLE001 - the note stays English
        pass
    if out.get("body"):
        out["body"] = f"{note}\n\n{out['body']}"
    if out.get("html"):
        import dl_proton
        out["html"] = dl_proton.insert_html(str(out["html"]), f"<p><i>{note}</i></p>")
    if not out.get("body") and not out.get("html"):
        out["body"] = note
    return out


# the prompt job running now ({"job": id, "session": Session}), so /schedule stop can interrupt it
RUNNING: dict = {}


# tools a job may use without "acting": a job that only read is run again after the server dropped it
READ_ONLY_TOOLS = {"view_file", "exa_web_search", "resolve_library_id", "get_library_docs", "syntax_guard", "mcp",
                   "switch_workspace"}


class JobRunner:
    """What dl_schedule.Scheduler needs from the daemon: run a job, check and warm the server, report."""

    def __init__(self, registry: "Registry"):
        self.registry = registry

    def main(self) -> Session:
        return self.registry.get(DEFAULT_SESSION)

    def post(self, title: str, text: str, level: str = "info") -> None:
        main = self.main()
        main.output(f"⏰ {title}", text)
        if level == "warn":
            main.notice(f"⏰ {title}", "warn")
        try:
            main.save()
        except Exception:  # noqa: BLE001 - the user's turn may be changing the history right now; its own save follows
            pass

    def notify(self, subject: str, body: str) -> None:
        to = str(dl_schedule.settings().get("notify_email") or "")
        if not to:
            return
        try:
            import dl_proton
            proton = dl_mcp.load_catalog()[0].get("proton")
            sender = (proton.fixed_args.get("from_address") if proton else "") or ""
            out = dl_proton.call("send_mail", {"to": to, "subject": subject, "body": body, "from_address": sender})
        except Exception as e:  # noqa: BLE001
            out = f"Error: {e}"
        if out.startswith("Error"):
            self.main().notice(f"⏰ could not email the notice: {out}", "warn")

    def health(self) -> bool:
        try:
            with cli.urllib.request.urlopen(f"{cli.DEFAULT_URL}/health", timeout=10) as r:
                return json.loads(r.read() or b"{}").get("status") == "ok"
        except Exception:  # noqa: BLE001
            return False

    def warm(self) -> None:
        req = cli.urllib.request.Request(f"{cli.DEFAULT_URL}/v1/load", data=b"{}", method="POST",
                                         headers={"Content-Type": "application/json",
                                                  "Authorization": f"Bearer {cli.DEFAULT_API_KEY}"})
        try:
            cli.urllib.request.urlopen(req, timeout=600).read()
        except Exception:  # noqa: BLE001 - busy means it is loaded; a failure shows when the job runs
            pass

    def run_action(self, job: dict) -> dict:
        """The exact action the user approved when scheduling it: no model, no second card."""
        tool, args = str(job["action"].get("tool")), dict(job["action"].get("args") or {})
        main = self.main()
        ws = Path(job.get("workspace") or main.workspace)
        ws = ws if ws.is_dir() else main.workspace
        reg = dl_mcp.McpRegistry(surface="code")
        dl_mcp.CALL.ctx = {"workspace": ws, "yolo": True, "request_time": time.time(), "registry": reg}
        if tool.endswith("send_mail") and float(job.get("late_s") or 0) > 120:
            args = add_late_note(args, float(job["planned_at"]), time.time())
        try:
            if "__" in tool:
                server = tool.split("__", 1)[0]
                out = reg.enable(server, f"scheduled job #{job['id']}")
                if out.startswith("error"):
                    return {"ok": False, "text": out}
            out = cli.dispatch_dl_tool(tool, args, ws, mode="act",
                                       session_context={"yolo": True, "approve": lambda *a: True, "mcp": reg})
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "text": f"{type(e).__name__}: {e}"}
        finally:
            reg.close()
        return {"ok": not str(out).lower().startswith(("error", "denied")), "text": str(out)}

    def run_prompt(self, job: dict) -> dict:
        """The agent in a session of its own; what it decides by itself asks on the Code tab's card."""
        main = self.main()
        ws = Path(job.get("workspace") or main.workspace)
        s = Session("dl-ai-schedule", ws if ws.is_dir() else main.workspace)
        s.effort = None                                # scheduled jobs keep effort None (the server's shared settings)
        calls: list[str] = []
        asked = []
        own_emit = s.emit

        def emit(ev: dict) -> None:
            if ev.get("type") == "tool_call":
                calls.append(str(ev.get("name")))
            own_emit(ev)

        def approve(kind: str, summary: str, reason: str) -> bool:
            if not asked:
                asked.append(1)
                self.notify(f"Ray: job #{job['id']} waits for your approval",
                            f"The scheduled job #{job['id']} wants to:\n\n{summary}\n\n({reason})\n\n"
                            "Answer it on the Code tab; it counts as a no after 30 minutes.")
            return main.approve(kind, f"[scheduled job #{job['id']}] {summary}", reason, cancel=s.cancel)

        s.emit, s.approve = emit, approve
        s.job_id = job["id"]                           # a job cannot schedule jobs (dl_schedule refuses it)
        s.yolo = bool(job.get("yolo"))                 # scheduled while YOLO was on: runs without asking too
        late = float(job.get("late_s") or 0)
        late_note = (f" It was planned for {dl_schedule.fmt(job['planned_at'])} and runs {late / 60:.0f} min late: "
                     "say so in any email you send." if late > 120 else "")
        prompt = (f"[Scheduled job #{job['id']} ({dl_schedule.describe(job['spec'])}).{late_note} Nobody is "
                  f"watching: do the task and end with the answer.]\n\n{job['prompt']}")

        def acted() -> bool:
            for name in calls:
                if name in READ_ONLY_TOOLS:
                    continue
                route = s.mcp.routes.get(name)
                if route and s.mcp._allowed_in("plan", *route):
                    continue
                return True
            return False
        RUNNING.update(job=job["id"], session=s)
        try:
            s._agent(prompt)
            if s.cancel.is_set():
                return {"ok": False, "text": "stopped with /schedule stop", "acted": acted(), "server_error": False}
            last = next((m for m in reversed(s.messages) if m.get("role") == "assistant" and m.get("content")), {})
            return {"ok": True, "text": plain(last.get("content") or ""), "acted": acted(), "server_error": False}
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            return {"ok": False, "text": msg, "acted": acted(),
                    "server_error": msg.startswith(("Strata API HTTP 5", "Connection failed to Strata"))}
        finally:
            RUNNING.clear()
            s.mcp.close()


class Registry:
    def __init__(self, default_ws: Path):
        self.default_ws = default_ws
        self.sessions: dict[str, Session] = {}
        self.lock = threading.Lock()

    def get(self, name: str | None) -> Session:
        name = name or DEFAULT_SESSION
        if not NAME_OK.match(name):
            raise ValueError("bad session name")
        with self.lock:
            if name not in self.sessions:
                self.sessions[name] = Session.load(name, self.default_ws)
            return self.sessions[name]


class Handler(socketserver.StreamRequestHandler):
    registry: Registry

    def send(self, obj: dict) -> None:
        self.wfile.write((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
        self.wfile.flush()

    def handle(self) -> None:
        attached: tuple[Session, queue.Queue] | None = None
        client_id = uuid.uuid4().hex[:8]
        try:
            for raw in self.rfile:
                try:
                    msg = json.loads(raw)
                    sess = self.registry.get(msg.get("session"))
                except (ValueError, TypeError) as e:
                    self.send({"type": "error", "text": f"bad request: {e}"})
                    continue
                op = msg.get("op")
                if op == "attach" and attached is None:
                    q: queue.Queue = queue.Queue()
                    with sess.lock:
                        sess.clients.add(q)
                        hello = {"type": "hello", "client": client_id, "state": sess.state(),
                                 "events": list(sess.events)}
                    attached = (sess, q)
                    self.send(hello)
                    threading.Thread(target=self._pump, args=(q,), daemon=True).start()
                    continue
                reply: dict = {"type": "ok"}
                if op == "input":
                    sess.submit(str(msg.get("text", "")), origin=msg.get("origin") or client_id,
                                effort=msg.get("effort") if msg.get("effort") in EFFORTS else None,
                                voice=msg.get("voice") is True)
                elif op in ("approve", "deny"):
                    if not sess.answer(str(msg.get("id", "")), op == "approve"):
                        reply = {"type": "error", "text": "no such approval (already answered?)"}
                elif op == "interrupt":
                    sess.interrupt()
                elif op == "export":
                    name, md = sess.export()
                    reply = {"type": "export", "filename": name, "markdown": md}
                elif op == "state":
                    reply = sess.state()
                else:
                    reply = {"type": "error", "text": f"unknown op {op!r}"}
                if attached is None:
                    self.send(reply)
                    return
                if reply["type"] == "error":
                    attached[1].put(reply)
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            if attached:
                sess, q = attached
                with sess.lock:
                    sess.clients.discard(q)
                q.put(None)

    def _pump(self, q: queue.Queue) -> None:
        try:
            while True:
                ev = q.get()
                if ev is None:
                    return
                self.send(ev)
        except (BrokenPipeError, ConnectionResetError, OSError, ValueError):
            return


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


def main() -> int:
    import argparse
    os.environ.setdefault("DL_CHECKPOINTS", "1")             # workspace checkpoints (cli.Checkpoints)
    os.environ.setdefault("DL_TRANSCRIPT", "1")              # every event to TRANSCRIPT_DIR
    ap = argparse.ArgumentParser(description="Ray shared CLI session daemon")
    ap.add_argument("--workspace", default=os.environ.get("STRATA_WORKSPACE_DIR") or os.getcwd())
    ap.add_argument("--socket", default=str(SOCKET_PATH))
    a = ap.parse_args()
    sock = Path(a.socket)
    sock.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(sock.parent, 0o700)
    try:                                   # a stale socket from a crash; a live daemon still answers it
        probe = socket.socket(socket.AF_UNIX)
        probe.connect(str(sock))
        probe.close()
        print(f"[dl-sessiond] already running on {sock}", file=sys.stderr)
        return 1
    except OSError:
        sock.unlink(missing_ok=True)
    Handler.registry = Registry(Path(a.workspace).expanduser().resolve())

    def _stop(*_):                         # systemd's SIGTERM: save the sessions and remove the socket
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, _stop)
    old = os.umask(0o177)
    srv = Server(str(sock), Handler)
    os.umask(old)
    print(f"[dl-sessiond] listening on {sock} (workspace {Handler.registry.default_ws})", flush=True)
    runner = JobRunner(Handler.registry)
    sched = dl_schedule.Scheduler(runner.run_prompt, runner.run_action, runner.health, runner.warm, runner.post,
                                  runner.notify)
    sched.start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        sched.stop.set()
        for s in Handler.registry.sessions.values():
            try:
                s.save()
            except OSError:
                pass
            s.mcp.close()                    # no browser or Google process outlives the daemon
        sock.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
