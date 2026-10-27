"""dl_attach.py - the terminal client of a shared D.L. AI session (tools/dl_sessiond.py).

    python3 tools/dl_cli.py --attach [session]

Shows the session's history, then streams it live; what you type goes to the same session the web app's Code tab
shows.  Ctrl-C interrupts a running turn, /detach (or Ctrl-D) leaves the session running.
"""
from __future__ import annotations

import json
import socket
import sys
import threading
from pathlib import Path

import dl_cli as cli
from dl_cli import (C_ACCENT, C_ACCENT_BOLD, C_BOLD, C_GREEN, C_INK_SOFT, C_MUTED, C_RED, C_RESET,  # noqa: F401
                    C_YELLOW)


class Renderer:
    def __init__(self, client_id: str = ""):
        self.client_id = client_id
        self.stream = None            # "thinking" | "text" while a block is open
        self.pending: str | None = None
        self.state: dict = {}

    def _close(self):
        if self.stream == "thinking":
            sys.stdout.write(f"{C_RESET}\n\n")
        elif self.stream == "text":
            sys.stdout.write("\n")
        self.stream = None

    def show(self, ev: dict, replay: bool = False) -> None:
        t = ev.get("type")
        w = sys.stdout.write
        if t == "thinking":
            if self.stream != "thinking":
                self._close()
                w(f"\n{C_ACCENT}🧠{C_RESET} {C_MUTED}Thinking:{C_RESET} {C_MUTED}")
                self.stream = "thinking"
            w(ev["text"])
        elif t == "text":
            if self.stream == "thinking":
                w(f"{C_RESET}\n\n")
            self.stream = "text"
            w(ev["text"])
        else:
            self._close()
            if t == "user":
                if replay or ev.get("origin") != self.client_id:
                    w(f"\n{C_ACCENT_BOLD}›{C_RESET} {C_BOLD}{ev['text']}{C_RESET}\n")
            elif t == "tool_call":
                w(f"{C_ACCENT}◆{C_RESET} {C_INK_SOFT}[Tool]{C_RESET} {C_BOLD}{ev['name']}{C_RESET}"
                  f"({C_MUTED}{cli.format_args_preview(ev.get('args') or {})}{C_RESET})\n")
            elif t == "tool_result":
                prev = ev.get("text", "")
                w(f"{C_MUTED}  ↳ {prev[:160] + ('...' if len(prev) > 160 else '')}{C_RESET}\n\n")
            elif t in ("output", "health"):
                if ev.get("title"):
                    w(f"\n{C_ACCENT}✦ {ev['title']}{C_RESET}\n")
                w(ev.get("ansi") or ev.get("text", ""))
                w("\n")
            elif t == "notice":
                color = {"warn": C_YELLOW, "error": C_RED}.get(ev.get("level"), C_GREEN)
                w(f"{color}{ev['text']}{C_RESET}\n")
            elif t == "error":
                w(f"{C_RED}Error: {ev['text']}{C_RESET}\n")
            elif t == "stats":
                w(f"{C_MUTED}[{ev['tokens']} tokens in {ev['seconds']}s · {ev['rate']} t/s]{C_RESET}\n")
            elif t == "approval_request" and not replay:
                self.pending = ev["id"]
                w(f"\n{C_YELLOW}⚠ {ev['summary']}{C_RESET} {C_MUTED}({ev['reason']}){C_RESET}\n"
                  f"  {C_ACCENT_BOLD}Allow?{C_RESET} type y or n (or answer in the web app)\n")
            elif t == "approval_resolved":
                if self.pending == ev["id"]:
                    self.pending = None
                if not replay:
                    w(f"{C_MUTED}  {'approved' if ev['ok'] else 'denied'}{C_RESET}\n")
            elif t == "state":
                self.state = ev
            elif t == "cleared":
                w(f"{C_MUTED}── conversation cleared ──{C_RESET}\n")
            elif t == "rewound" and not replay and ev.get("origin") == self.client_id and ev.get("cmd") != "/edit":
                w(f"{C_MUTED}The prompt was:{C_RESET} {ev.get('text', '')}\n")
            elif t == "restored":                       # /resume, /rewind, /edit, /branch: drawn as a replay
                self._close()
                w(f"\n{C_MUTED}── resumed: {ev.get('title') or '(untitled)'} ──{C_RESET}\n")
                for e in ev.get("events") or []:
                    self.show(e, replay=True)
                self._close()
        sys.stdout.flush()


def attach(session: str = "dl-ai-code", sock_path: Path | None = None) -> int:
    import dl_sessiond
    path = sock_path or dl_sessiond.SOCKET_PATH
    s = socket.socket(socket.AF_UNIX)
    try:
        s.connect(str(path))
    except OSError as e:
        print(f"{C_RED}No session daemon at {path} ({e}). Start it: systemctl --user start dl-ai-sessiond{C_RESET}")
        return 1
    f = s.makefile("rwb")

    def send(**msg):
        f.write((json.dumps({"session": session, **msg}) + "\n").encode())
        f.flush()

    send(op="attach")
    hello = json.loads(f.readline())
    r = Renderer(hello.get("client", ""))
    r.state = hello.get("state", {})
    for ev in hello.get("events", []):
        r.show(ev, replay=True)
    for p in r.state.get("pending", []):
        r.show({"type": "approval_request", **p})
    st = r.state
    print(f"\n{C_GREEN}✓ Attached to session {C_BOLD}{session}{C_RESET}{C_GREEN} · {st.get('workspace')} · "
          f"{st.get('mode', 'act').upper()} mode{C_RESET}  {C_MUTED}(/detach to leave it running){C_RESET}\n")

    done = threading.Event()

    def reader():
        try:
            for line in f:
                r.show(json.loads(line))
        except (OSError, ValueError):
            pass
        done.set()
        print(f"\n{C_RED}Session daemon disconnected.{C_RESET}")

    threading.Thread(target=reader, daemon=True).start()
    while not done.is_set():
        try:
            line = input("")
        except EOFError:
            break
        except KeyboardInterrupt:
            if r.state.get("busy"):
                send(op="interrupt")
                print(f"{C_YELLOW}Interrupt sent.{C_RESET}")
            else:
                print(f"{C_MUTED}(/detach to leave){C_RESET}")
            continue
        text = line.strip()
        if not text:
            continue
        if text in ("/detach", "/exit", "/quit"):
            break
        if r.pending and text.lower() in ("y", "yes", "n", "no"):
            send(op="approve" if text.lower().startswith("y") else "deny", id=r.pending)
            continue
        send(op="input", text=text, origin=r.client_id)
    s.close()
    print(f"{C_MUTED}Detached; the session keeps running.{C_RESET}")
    return 0
