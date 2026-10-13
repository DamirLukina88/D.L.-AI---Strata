#!/usr/bin/env python3
"""dl_sessiond.py - D.L. AI shared CLI sessions: one agent session, driven from any number of clients at once.

The agent (dl_cli's loop, tools and prompts) runs here, not in a terminal.  Clients attach over a Unix socket and
all see the same live event stream: the terminal (`dl_cli.py --attach`) and the web app's Code tab (bridged by
serve/server.py at /api/code/session).  Start a task on the phone, continue it in Konsole, and back.

Protocol: JSON lines on $XDG_RUNTIME_DIR/dl-ai/sessiond.sock (mode 600).
  {"op": "attach", "session": "dl-ai-code"}       -> {"type": "hello", "state": {...}, "events": [...]}, then live
  {"op": "input", "session": ..., "text": "..."}  a prompt, a /command or !shell
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
from dl_auditing import format_health_card, get_system_health  # noqa: E402

RUNTIME = Path(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}") / "dl-ai"
SOCKET_PATH = RUNTIME / "sessiond.sock"
STATE_DIR = Path.home() / ".local" / "state" / "dl-ai" / "sessions"
DEFAULT_SESSION = "dl-ai-code"
REPLAY_MAX = 3000                 # events kept for a client that attaches later
APPROVAL_TIMEOUT = 30 * 60        # an unanswered approval is a "no"
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
NAME_OK = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")

EXECUTE_PLAN = ("Proceed with executing the plan now. Perform the necessary tool calls (edits, writes, tests, "
                "commands) to implement the agreed plan.")


def plain(text: str) -> str:
    return ANSI.sub("", text or "")


_save_lock = threading.Lock()


class Session:
    def __init__(self, name: str, workspace: Path):
        self.name = name
        self.workspace = workspace
        self.mode = "act"
        self.think = "medium"
        self.yolo = False
        self.messages: list[dict] = [{"role": "system", "content": cli.build_dl_system_prompt(workspace, "act")}]
        self.events: list[dict] = []
        self.seq = 0
        self.clients: set[queue.Queue] = set()
        self.lock = threading.RLock()
        self.busy = False
        self.cancel = threading.Event()
        self.pending: dict[str, dict] = {}       # approval id -> {"event", "ok", "kind", ...}
        self.plan_offer: str | None = None       # id of an open "Execute this plan?" offer

    # ---------------------------------------------------------------- events
    def emit(self, ev: dict) -> None:
        with self.lock:
            self.seq += 1
            ev = {**ev, "seq": self.seq, "ts": round(time.time(), 3)}
            last = self.events[-1] if self.events else None
            merge = bool(last and ev["type"] in ("thinking", "text") and last["type"] == ev["type"])
            if ev["type"] in ("thinking", "text"):             # a stable id for the block, live and in replay
                ev["block"] = last.get("block", last["seq"]) if merge else self.seq
            if merge:
                last["text"] += ev["text"]                     # replay keeps one block, live clients get deltas
                last["seq"] = ev["seq"]
            else:
                self.events.append(dict(ev))
                if len(self.events) > REPLAY_MAX:
                    del self.events[:len(self.events) - REPLAY_MAX]
            for q in list(self.clients):
                q.put(ev)

    def state(self) -> dict:
        return {"type": "state", "session": self.name, "workspace": str(self.workspace), "mode": self.mode,
                "think": self.think, "yolo": self.yolo, "busy": self.busy,
                "wiki": str(cli.resolve_wiki_root(self.workspace) or ""),
                "pending": [{"id": k, "kind": v["kind"], "summary": v["summary"], "reason": v["reason"]}
                            for k, v in self.pending.items()]}

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
            data = {"name": self.name, "workspace": str(self.workspace), "mode": self.mode, "think": self.think,
                    "messages": self.messages, "events": self.events[-REPLAY_MAX:], "seq": self.seq}
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            tmp = self.path().with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False))
            os.chmod(tmp, 0o600)
            tmp.replace(self.path())

    @classmethod
    def load(cls, name: str, default_ws: Path) -> "Session":
        p = STATE_DIR / f"{name}.json"
        try:
            data = json.loads(p.read_text())
        except (OSError, ValueError):
            return cls(name, default_ws)
        ws = Path(data.get("workspace") or default_ws)
        s = cls(name, ws if ws.is_dir() else default_ws)
        s.mode = data.get("mode", "act")
        s.think = data.get("think", "medium")
        s.messages = data.get("messages") or s.messages
        s.messages[0] = {"role": "system", "content": cli.build_dl_system_prompt(s.workspace, s.mode)}
        s.events = data.get("events") or []
        s.seq = int(data.get("seq") or len(s.events))
        return s

    # ---------------------------------------------------------------- approvals
    def approve(self, kind: str, summary: str, reason: str) -> bool:
        """The dl_cli approver: ask every attached client, wait for the first answer."""
        aid = uuid.uuid4().hex[:10]
        ev = threading.Event()
        with self.lock:
            self.pending[aid] = {"event": ev, "ok": False, "kind": kind, "summary": summary, "reason": reason}
        self.emit({"type": "approval_request", "id": aid, "kind": kind, "summary": summary, "reason": reason})
        deadline = time.time() + APPROVAL_TIMEOUT
        while not ev.wait(0.5):
            if self.cancel.is_set() or time.time() > deadline:
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
    def submit(self, text: str, origin: str = "") -> None:
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
        threading.Thread(target=self._run, args=(text, origin), daemon=True).start()

    def _run(self, text: str, origin: str) -> None:
        self.emit({"type": "user", "text": text, "origin": origin})
        self.emit_state()
        try:
            prompt = self._command(text)
            if prompt is not None:
                self._agent(prompt)
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
        self.messages[0] = {"role": "system", "content": cli.build_dl_system_prompt(self.workspace, self.mode)}

    def _transcript(self, prompt: str, out: str) -> None:
        self.messages.append({"role": "user", "content": prompt})
        self.messages.append({"role": "assistant", "content": plain(out)})

    def _agent(self, prompt: str) -> None:
        self.messages.append({"role": "user", "content": cli.resolve_file_references(prompt, self.workspace)})
        ctx = {"workspace": self.workspace, "messages": self.messages, "mode": self.mode, "yolo": self.yolo,
               "emit": self.emit, "cancel": self.cancel, "approve": self.approve}
        new_ws = cli.execute_agent_loop(messages=self.messages, url=cli.DEFAULT_URL, api_key=cli.DEFAULT_API_KEY,
                                        workspace=self.workspace, think_level=self.think, mode=self.mode,
                                        session_context=ctx)
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
        if not text.startswith("/"):
            return text
        cmd, _, arg = text.partition(" ")
        arg = arg.strip()
        if cmd in ("/act", "/execute"):
            self.mode = "act"
            self._system()
            self.emit_state()
            return arg or EXECUTE_PLAN
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
        if cmd == "/yolo":
            self.yolo = not self.yolo
            self.notice("YOLO on: destructive actions run without asking." if self.yolo
                        else "Approvals back on for destructive actions.", "warn" if self.yolo else "info")
            return None
        if cmd in ("/clear", "/reset"):
            self.messages = [{"role": "system", "content": cli.build_dl_system_prompt(self.workspace, self.mode)}]
            with self.lock:
                self.events = []
            self.emit({"type": "cleared"})
            self.notice(f"Memory reset ({self.mode} mode).")
            return None
        if cmd == "/think":
            val = {"med": "medium"}.get(arg.lower(), arg.lower())
            if val in ("none", "low", "medium", "high"):
                self.think = val
                self.notice(f"Reasoning effort: {val}.")
            else:
                self.notice(f"Reasoning effort is {self.think}. Usage: /think none|low|medium|high")
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
            name, md = self.export()
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

    def export(self) -> tuple[str, str]:
        stamp = datetime.datetime.now().strftime("%Y-%m-%d-%H-%M")
        return (f"dl-ai-code-chat-{stamp}.md",
                cli.format_messages_to_markdown(self.messages, workspace=self.workspace))


HELP = """/plan [task]      Plan Mode: read-only research, ends with "Execute this plan?"
/act [task]       Act Mode (executes the agreed plan when given no task)
/yolo             Toggle approvals for destructive actions
/think <level>    none | low | medium | high
/cd <path>        Change the working directory (the wiki follows it)
/status /health   Engine status, hardware health
/exa <q>          Web search      /context7 <lib>  Library docs
/diff /secrets /test [files] /wiki [search|lint|digest]
/save [file]      Save the chat as Markdown in the workspace
/clear            Reset the conversation
!<command>        Run a shell command in the workspace"""


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
                    sess.submit(str(msg.get("text", "")), origin=msg.get("origin") or client_id)
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
    ap = argparse.ArgumentParser(description="D.L. AI shared CLI session daemon")
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
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        for s in Handler.registry.sessions.values():
            try:
                s.save()
            except OSError:
                pass
        sock.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
