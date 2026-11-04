#!/usr/bin/env python3
"""helmet_test.py - times Ray's voice drawer through a Bluetooth helmet (the Sena), lined up on the PC's clock.

    python3 tools/helmet_test.py check                  what it found: phone, helmet, PC mic, server, session daemon
    python3 tools/helmet_test.py record [--steps baseline]   records while you do the steps it shows
    python3 tools/helmet_test.py restore                undoes the test-time phone settings (also done on exit)
    python3 tools/helmet_test.py probe [--modes vr,call,vr]  records the helmet's mic each way while you count aloud

You hold the helmet in front of the Blue Snowball and talk into the helmet's mic; the Snowball hears your voice and the
helmet's speaker (Ray's answer, the helmet's own tones, music).  Meanwhile it records, into
~/.local/share/dl-ai/helmet-tests/<date-time>/ (outside the repo: it holds your voice):

    audio.wav            the Snowball, 16 kHz mono
    audio_anchors.jsonl  PC wall time at sample counts, every 0.5 s (puts the audio on the PC clock)
    logcat.txt           the phone's live log (main, system, crash, events), epoch seconds
    server-journal.txt   the Strata server's journal (prompt, thinking, done, tts lines), epoch seconds
    sessiond.jsonl       the shared Ray session's live events, stamped with PC time on arrival (read only)
    clock.jsonl          phone clock minus PC clock, from the fastest of several adb round trips
    marks.jsonl          when each step was shown, started and finished, and what you noticed
    snap-NN-<step>/      dumpsys audio, bluetooth_manager, media_session, window, power, connectivity, the app's trace

The phone is reached by its USB serial (the Wi-Fi link drops when the tunnel steps turn Wi-Fi off, and with two
links plain `adb` refuses to pick one).  Settings changed for the test are written to .pending-restore.json first and
undone when the run ends, Ctrl-C included, or by `restore`: the log buffer (16 MB), the battery shown as unplugged
(the cable's charging otherwise keeps the screen on, developer option "stay awake", and changes HyperOS power rules)
and Wi-Fi (off for the tunnel steps).
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import wave
from pathlib import Path

PACKAGE = "com.damirl.ray"
BASE = Path.home() / ".local/share/dl-ai/helmet-tests"
PENDING = BASE / ".pending-restore.json"
SESSIOND_SOCKET = Path(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}") / "dl-ai" / "sessiond.sock"
# no adb fallback in tools/phone_mcp.py while this file exists: phone tools then work as they would on the road
ADB_OFF_FLAG = SESSIOND_SOCKET.parent / "phone-adb-off"
RATE = 16000
TEST_LOG_SIZE = "16M"

# The baseline: one press per case on the installed build, prompts that need no phone tool
BASELINE = [
    {"id": "lan-unlocked", "net": "wifi", "lock": "unlocked", "prompt": "What time is it?"},
    {"id": "lan-locked", "net": "wifi", "lock": "screen_off", "prompt": "How warm is it in Zagreb right now?"},
    {"id": "tunnel-unlocked", "net": "mobile", "lock": "unlocked", "prompt": "What day is it today?"},
    {"id": "tunnel-locked", "net": "mobile", "lock": "screen_off", "prompt": "Tell me a fun fact about red pandas."},
]
# The same four cases with the helmet worn: on the desk its mic hardly hears you and its noise gate sent zeros
# (mic tests 2026-11-04), so the Snowball now only times your voice; Ray's answer is timed from the phone's trace
RECHECK = [
    {"id": "lan-unlocked", "net": "wifi", "lock": "unlocked", "prompt": "What time is it?"},
    {"id": "lan-locked", "net": "wifi", "lock": "screen_off", "prompt": "How warm is it in Zagreb right now?"},
    {"id": "tunnel-unlocked", "net": "mobile", "lock": "unlocked", "prompt": "What day is it today?"},
    {"id": "tunnel-locked", "net": "mobile", "lock": "screen_off", "prompt": "Tell me a fun fact about red pandas."},
]
# Round 2 on the fixed build: music playing (does it pause for Ray and come back?), the lock screen showing, and more
# plain presses for the old "sometimes nothing opens"
ROUND2 = [
    {"id": "lan-unlocked-music", "net": "wifi", "lock": "unlocked", "music": True, "prompt": "What time is it?"},
    {"id": "lan-locked-music", "net": "wifi", "lock": "screen_off", "music": True, "prompt": "What day is it today?"},
    {"id": "lan-lockscreen", "net": "wifi", "lock": "lock_screen", "prompt": "Tell me a short joke."},
    {"id": "lan-unlocked", "net": "wifi", "lock": "unlocked", "prompt": "What time is it?"},
    {"id": "lan-locked", "net": "wifi", "lock": "screen_off", "prompt": "What's the date today?"},
    {"id": "tunnel-locked-music", "net": "mobile", "lock": "screen_off", "music": True, "prompt": "What time is it?"},
    {"id": "tunnel-unlocked", "net": "mobile", "lock": "unlocked", "prompt": "What day is it today?"},
    {"id": "tunnel-locked", "net": "mobile", "lock": "screen_off", "prompt": "Tell me a short joke."},
]
# Round 3: three with music, three without; locked steps wait 10 s so the phone dozes (the drawer the system hid,
# round 2)
ROUND3 = [
    {"id": "lan-locked-music", "net": "wifi", "lock": "screen_off", "doze": True, "music": True, "prompt": "What time is it?"},
    {"id": "lan-locked", "net": "wifi", "lock": "screen_off", "doze": True, "music": False, "prompt": "What day is it today?"},
    {"id": "lan-unlocked-music", "net": "wifi", "lock": "unlocked", "music": True, "prompt": "Tell me a short joke."},
    {"id": "tunnel-locked-music", "net": "mobile", "lock": "screen_off", "doze": True, "music": True, "prompt": "What time is it?"},
    {"id": "tunnel-locked", "net": "mobile", "lock": "screen_off", "doze": True, "music": False, "prompt": "What's the date today?"},
    {"id": "tunnel-unlocked", "net": "mobile", "lock": "unlocked", "music": False, "prompt": "What day is it today?"},
]
STEP_SETS = {"baseline": BASELINE, "recheck": RECHECK, "round2": ROUND2, "round3": ROUND3}
SETUP = {
    "baseline": "Hold the helmet in front of the Snowball and talk into the helmet's mic; keep the phone on the desk.",
    "recheck": "Wear the helmet as when you ride, near the PC (the Snowball hears your voice); keep the phone on the "
               "desk. Don't change the phone's Wi-Fi yourself: the tool does it.",
    "round2": "Wear the helmet as when you ride, near the PC; keep the phone on the desk. Don't change the phone's "
              "Wi-Fi yourself: the tool does it. Music steps: play a song in YouTube Music (Brave) first.",
    "round3": "Wear the helmet as when you ride, near the PC; keep the phone on the desk. Don't change the phone's "
              "Wi-Fi yourself: the tool does it. Music steps: play a song in YouTube Music (Brave) first; in the "
              "other steps pause it first.",
}

LOCK_HOW = {
    "unlocked": "Unlock the phone and go to the home screen (Ray's app closed or in the background).",
    "screen_off": "Press the phone's power button so the screen goes dark (it locks). Leave it dark.",
    "lock_screen": "Lock the phone (power button), then press power once more so the lock screen shows. Don't unlock.",
}
NET_NAME = {"wifi": "LAN (home Wi-Fi)", "mobile": "Cloudflare tunnel (mobile data, Wi-Fi off)"}


# ---------------------------------------------------------------- small helpers

def sh(args: list[str], timeout: float = 15.0) -> str:
    """Runs a command and returns its stdout ('' when it failed)."""
    try:
        res = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return res.stdout if res.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def usb_serial() -> str | None:
    """The phone's USB serial from `adb devices` (a wireless link has a ':' or an mDNS name)."""
    for line in sh(["adb", "devices"]).splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device" and ":" not in parts[0] and "._adb" not in parts[0]:
            return parts[0]
    return None


class Phone:
    def __init__(self, serial: str):
        self.serial = serial

    def shell(self, cmd: str, timeout: float = 15.0) -> str:
        return sh(["adb", "-s", self.serial, "shell", cmd], timeout)

    def clock_offset(self, tries: int = 7) -> dict:
        """Phone clock minus PC clock in seconds, from the round trip with the least delay."""
        best = None
        for _ in range(tries):
            t0 = time.time()
            out = sh(["adb", "-s", self.serial, "shell", "date +%s%N"], 5)
            t1 = time.time()
            if not out.strip().isdigit():
                continue
            phone = int(out.strip()) / 1e9
            sample = {"offset": phone - (t0 + t1) / 2, "rtt": t1 - t0, "pc": (t0 + t1) / 2}
            if best is None or sample["rtt"] < best["rtt"]:
                best = sample
        return best or {"offset": None, "rtt": None, "pc": time.time()}

    def lock_state(self) -> dict:
        window = self.shell("dumpsys window")
        power = self.shell("dumpsys power")
        keyguard = re.search(r"isKeyguardShowing=(\w+)", window)
        wake = re.search(r"mWakefulness=(\w+)", power)
        return {"keyguard": keyguard.group(1) == "true" if keyguard else None,
                "wakefulness": wake.group(1) if wake else None}

    def network(self) -> dict:
        """Wi-Fi on/off and which transport carries the default network (AdGuard's VPN sits on top of it)."""
        conn = self.shell("dumpsys connectivity")
        status = self.shell("cmd wifi status").splitlines()
        wifi_on = ("enabled" in status[0]) if status else None      # "Wifi is enabled" / "Wifi is disabled"
        default = re.search(r"Active default network: (\d+)", conn)
        transport = None
        if default:
            m = re.search(r"NetworkAgentInfo\{network\{%s\}.*?ni\{(\w+)" % default.group(1), conn)
            transport = m.group(1) if m else None
        return {"wifi_on": wifi_on, "default": transport}

    def brave_playing(self) -> bool | None:
        """True when Brave's media session (YouTube Music) is PLAYING, from dumpsys media_session."""
        dump = self.shell("dumpsys media_session")
        block = dump.split("package=com.brave.browser", 1)
        if len(block) < 2:
            return None
        m = re.search(r"state=PlaybackState \{state=(\w+)", block[1])
        return m.group(1).startswith("PLAYING") if m else None

    def helmet(self) -> dict:
        """The active headset (HFP) and music (A2DP) devices' names, from the Bluetooth dump."""
        bt = self.shell("dumpsys bluetooth_manager", 25)
        active = re.findall(r"^\s+\S+: (.+?) <- ACTIVE", bt, re.M)
        return {"active": active, "sena": sum("SENA" in a.upper() for a in active) >= 2}

    def set_wifi(self, on: bool) -> None:
        state = "enabled" if on else "disabled"
        if not self.shell(f"cmd wifi set-wifi-enabled {state}"):
            self.shell(f"svc wifi {'enable' if on else 'disable'}")


# ---------------------------------------------------------------- what runs during a recording

class AudioRecorder(threading.Thread):
    """The PC mic through PulseAudio/PipeWire (pacat, raw 16 kHz mono), with PC-time anchors every 0.5 s."""

    def __init__(self, source: str, out: Path):
        super().__init__(daemon=True)
        self.out = out
        self.samples = 0
        self.proc = subprocess.Popen(
            ["pacat", "--record", "--raw", "--format=s16le", f"--rate={RATE}", "--channels=1",
             f"--device={source}", "--latency-msec=20"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)

    def run(self) -> None:
        fd = self.proc.stdout.fileno()
        last = 0.0
        with open(self.out / "audio.raw", "wb") as raw, open(self.out / "audio_anchors.jsonl", "w") as anchors:
            while True:
                chunk = os.read(fd, 4096)
                if not chunk:
                    break
                now = time.time()
                raw.write(chunk)
                self.samples += len(chunk) // 2
                if now - last >= 0.5:
                    anchors.write(json.dumps({"pc": now, "samples": self.samples}) + "\n")
                    anchors.flush()
                    last = now

    def stop(self) -> None:
        self.proc.terminate()
        try:
            self.proc.wait(5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.join(5)
        raw = self.out / "audio.raw"
        if raw.exists():
            with wave.open(str(self.out / "audio.wav"), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(RATE)
                w.writeframes(raw.read_bytes())
            raw.unlink()


class SessionWatcher(threading.Thread):
    """Attaches to the shared Ray session as one more client and only reads: each live event, stamped on arrival."""

    def __init__(self, out: Path, session: str = "dl-ai-code"):
        super().__init__(daemon=True)
        self.out = out
        self.session = session
        self.sock: socket.socket | None = None
        self.ok = False

    def run(self) -> None:
        try:
            self.sock = socket.socket(socket.AF_UNIX)
            self.sock.connect(str(SESSIOND_SOCKET))
            self.sock.sendall((json.dumps({"op": "attach", "session": self.session}) + "\n").encode())
            f = self.sock.makefile("rb")
            with open(self.out / "sessiond.jsonl", "w") as log:
                for line in f:
                    now = time.time()
                    try:
                        ev = json.loads(line)
                    except ValueError:
                        continue
                    if ev.get("type") == "hello":       # the session's history: kept out, only the count
                        self.ok = True
                        ev = {"type": "hello", "events": len(ev.get("events") or [])}
                    log.write(json.dumps({"pc": now, "ev": ev}, ensure_ascii=False) + "\n")
                    log.flush()
        except OSError:
            pass

    def stop(self) -> None:
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass


class Recording:
    def __init__(self, phone: Phone, source: str, out: Path):
        self.phone = phone
        self.out = out
        self.audio = AudioRecorder(source, out)
        self.watcher = SessionWatcher(out)
        self.procs: list[subprocess.Popen] = []
        self.snaps = 0

    def _spawn(self, args: list[str], name: str) -> None:
        f = open(self.out / name, "w")
        self.procs.append(subprocess.Popen(args, stdout=f, stderr=subprocess.DEVNULL))

    def start(self) -> None:
        self.audio.start()
        self.watcher.start()
        self._spawn(["adb", "-s", self.phone.serial, "logcat", "-v", "epoch", "-b", "main,system,crash,events"],
                    "logcat.txt")
        self._spawn(["journalctl", "--user", "-u", "strata-server", "-f", "-n", "0", "-o", "short-unix"],
                    "server-journal.txt")
        self.clock("start")

    def clock(self, label: str) -> dict:
        c = self.phone.clock_offset()
        c["label"] = label
        with open(self.out / "clock.jsonl", "a") as f:
            f.write(json.dumps(c) + "\n")
        return c

    def mark(self, kind: str, **extra) -> None:
        with open(self.out / "marks.jsonl", "a") as f:
            f.write(json.dumps({"pc": time.time(), "kind": kind, **extra}, ensure_ascii=False) + "\n")

    def snapshot(self, label: str) -> Path:
        self.snaps += 1
        d = self.out / f"snap-{self.snaps:02d}-{label}"
        d.mkdir()
        for name, cmd in [("audio", "dumpsys audio"), ("bluetooth", "dumpsys bluetooth_manager"),
                          ("media_session", "dumpsys media_session"), ("window", "dumpsys window"),
                          ("power", "dumpsys power"), ("connectivity", "dumpsys connectivity")]:
            (d / f"{name}.txt").write_text(self.phone.shell(cmd, 30))
        trace = sh(["adb", "-s", self.phone.serial, "exec-out", "run-as", PACKAGE, "cat", "files/voice_trace.jsonl"])
        if trace.startswith("{"):                      # not "cat: ...: No such file" (a build without the trace)
            (d / "voice_trace.jsonl").write_text(trace)
        return d

    def stop(self) -> None:
        self.clock("end")
        for p in self.procs:
            p.terminate()
        for p in self.procs:
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                p.kill()
        self.watcher.stop()
        self.audio.stop()


# ---------------------------------------------------------------- test-time settings, always undone

def pending() -> dict:
    try:
        return json.loads(PENDING.read_text())
    except (OSError, ValueError):
        return {}


def note_pending(**changes) -> None:
    state = pending()
    state.update(changes)
    BASE.mkdir(parents=True, exist_ok=True)
    PENDING.write_text(json.dumps(state))


def log_size(phone: Phone) -> str:
    m = re.search(r"main: ring buffer is (\d+) (\w)iB", sh(["adb", "-s", phone.serial, "logcat", "-g"]))
    return f"{m.group(1)}{m.group(2)}" if m else "2M"


def restore(phone: Phone | None = None) -> list[str]:
    """Undoes whatever .pending-restore.json lists; returns what was done."""
    state = pending()
    if not state:
        return []
    phone = phone or Phone(state.get("serial") or usb_serial() or "")
    done = []
    if state.get("wifi_off"):
        phone.set_wifi(True)
        done.append("Wi-Fi on")
    if state.get("battery"):
        phone.shell("dumpsys battery reset")
        done.append("battery reset")
    if state.get("log_size"):
        sh(["adb", "-s", phone.serial, "logcat", "-G", state["log_size"]])
        done.append(f"log buffer {state['log_size']}")
    if state.get("adb_off") and ADB_OFF_FLAG.exists():
        ADB_OFF_FLAG.unlink()
        done.append("adb fallback back on")
    PENDING.unlink(missing_ok=True)
    return done


# ---------------------------------------------------------------- the mic test (MicProbeActivity)

def pull(phone: Phone, name: str, dest: Path) -> bool:
    """Copies the app's files/<name> to dest (a debug build: run-as)."""
    try:
        data = subprocess.run(["adb", "-s", phone.serial, "exec-out", "run-as", PACKAGE, "cat", f"files/{name}"],
                              capture_output=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    if not data or data.startswith(b"run-as:") or data.startswith(b"cat:"):
        return False
    dest.write_bytes(data)
    return True


def transcribe(wav: Path) -> str:
    """Whisper (whisper-cli, the server's model) on a short recording; '' when it isn't installed."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "serve"))
    try:
        from transcribe import get_default_model_path
        model = get_default_model_path()
    except ImportError:
        model = None
    if not model or not shutil.which("whisper-cli"):
        return ""
    out = sh(["whisper-cli", "-m", model, "-f", str(wav), "-l", "en", "-np", "-nt", "-t", "4"], 120)
    return " ".join(out.split())


def run_probes(phone: Phone, modes: list[str], seconds: int) -> None:
    out = BASE / (datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S") + "-probe")
    out.mkdir(parents=True)
    print(f"Mic test into {out}")
    print("Put the helmet on, as when you ride (its mic at your mouth). In each test count slowly at your normal "
          "riding voice: one, two, three, ...")
    results = []
    for n, variant in enumerate(modes, 1):
        # link[/source[/audio mode]]: vr or call; vr (VOICE_RECOGNITION), comm (VOICE_COMMUNICATION) or mic; normal or comm
        mode, source, audio_mode = (variant.split("/") + ["vr", "normal"])[:3]
        name = {"vr": "voice recognition", "call": "call link"}.get(mode, mode) + (
            f", {source} source, {audio_mode} mode" if "/" in variant else "")
        ask(f"\n=== Test {n} of {len(modes)} ({name}): press Enter, "
            f"then start counting at once and keep going for {seconds} s. ")
        started = time.time()
        phone.shell(f"am start -n {PACKAGE}/.audio.MicProbeActivity --es mode {mode} --ei seconds {seconds} "
                    f"--es source {source} --es audio_mode {audio_mode}")
        print("    recording… keep counting")
        time.sleep(seconds + 4)
        print("    stop counting.")
        info = {}
        tag = variant.replace("/", "-")
        if pull(phone, "mic_probe.json", out / f"probe{n}-{tag}.json"):
            info = json.loads((out / f"probe{n}-{tag}.json").read_text())
        wav = out / f"probe{n}-{tag}.wav"
        heard = transcribe(wav) if pull(phone, "mic_probe.wav", wav) else ""
        levels = info.get("levels_db") or []
        # the Sena's noise gate sends exact zeros (-90.3 dB here) until it lets speech through
        sound = next((i * 0.1 for i, db in enumerate(levels) if db > -85), None)
        open_share = sum(db > -85 for db in levels) / len(levels) if levels else 0
        row = {"mode": variant, "device_type": info.get("device_type"), "link_s": (info.get("link_ms") or 0) / 1000,
               "peak_db": max(levels) if levels else None, "first_sound_s": sound, "open_share": open_share,
               "heard": heard, "asked_pc": started}
        results.append(row)
        print(f"    link {row['link_s']:.2f} s, mic {'helmet' if row['device_type'] == 7 else row['device_type']}, "
              f"peak {row['peak_db']} dB, first sound at {sound if sound is None else round(sound, 1)} s, "
              f"sound in {open_share:.0%} of the test")
        print(f"    heard: {heard or '(nothing)'}")
        time.sleep(2)
    (out / "results.json").write_text(json.dumps(results, indent=1))
    print(f"\nSaved in {out}")


# ---------------------------------------------------------------- checks and the guided steps

def snowball_source() -> str | None:
    for line in sh(["pactl", "list", "sources", "short"]).splitlines():
        parts = line.split("\t")
        if len(parts) > 1 and "Snowball" in parts[1] and parts[1].startswith("alsa_input"):
            return parts[1]
    return None


def check(serial: str | None) -> dict:
    found = {"serial": serial, "snowball": snowball_source(), "sessiond": SESSIOND_SOCKET.exists(),
             "pacat": bool(shutil.which("pacat")), "whisper": bool(shutil.which("whisper-cli"))}
    if serial:
        phone = Phone(serial)
        found.update(lock=phone.lock_state(), network=phone.network(), helmet=phone.helmet(),
                     clock=phone.clock_offset(3))
    return found


def ask(prompt: str) -> str:
    try:
        return input(prompt)
    except EOFError:
        return ""


def ensure_network(phone: Phone, rec: Recording, want: str) -> None:
    net = phone.network()
    if want == "mobile" and net["wifi_on"]:
        print("\n>>> Turning the phone's Wi-Fi off: the next steps go through the Cloudflare tunnel on mobile data.")
        note_pending(wifi_off=True)
        rec.mark("wifi", on=False)
        phone.set_wifi(False)
    elif want == "wifi" and net["wifi_on"] is False:
        print("\n>>> Turning the phone's Wi-Fi back on (LAN steps).")
        phone.set_wifi(True)
        note_pending(wifi_off=False)
        rec.mark("wifi", on=True)
    else:
        return
    end = time.time() + 45
    while time.time() < end:
        time.sleep(2)
        net = phone.network()
        if (want == "mobile" and net["default"] == "MOBILE") or (want == "wifi" and net["default"] == "WIFI"):
            break
    print(f"    phone network now: Wi-Fi {'on' if net['wifi_on'] else 'off'}, default {net['default']}")
    rec.mark("network", **net)
    time.sleep(3)                                    # let the app see the change before the next press


def lock_ok(state: dict, want: str) -> bool:
    if want == "unlocked":
        return state["keyguard"] is False and state["wakefulness"] == "Awake"
    if want == "screen_off":
        return state["keyguard"] is True and state["wakefulness"] != "Awake"
    return state["keyguard"] is True and state["wakefulness"] == "Awake"


def run_steps(phone: Phone, rec: Recording, steps: list[dict]) -> None:
    for n, step in enumerate(steps, 1):
        ensure_network(phone, rec, step["net"])
        print(f"\n=== Step {n} of {len(steps)}: {NET_NAME[step['net']]}, {step['lock'].replace('_', ' ')} ===")
        if step.get("music"):
            print("    First play a song in YouTube Music (Brave) so you hear it in the helmet, and leave it playing.")
        if step.get("music") is False:
            print("    Pause the music first (no song playing in this step).")
        print(f"    {LOCK_HOW[step['lock']]}")
        if step.get("doze"):
            print("    Then wait 10 seconds before pressing Enter (the phone goes into its always-on screen).")
        rec.mark("shown", step=step["id"], n=n)
        while True:
            ask("    Done? Press Enter. ")
            state = phone.lock_state()
            playing = phone.brave_playing() if step.get("music") else None
            if step.get("music") and playing is not True:
                print("    Brave isn't playing yet. Start the song, then press Enter (or type s and Enter to go on anyway).")
                if ask("    ").strip().lower() == "s":
                    break
                continue
            if lock_ok(state, step["lock"]):
                break
            print(f"    The phone looks different (lock screen showing: {state['keyguard']}, screen: "
                  f"{state['wakefulness']}). Set it as above and press Enter, or type s and Enter to go on anyway.")
            if ask("    ").strip().lower() == "s":
                break
        rec.mark("ready", step=step["id"], **state)
        print(f"\n    NOW: hold the helmet's button until the two beeps, then say:  «{step['prompt']}»")
        print("    Speak as you normally would. When Ray has answered (or nothing happened for 20 s), come back here.")
        if step.get("music"):
            print("    After his answer, wait 5 s: does the song come back in the helmet?")
        rec.mark("go", step=step["id"], prompt=step["prompt"])
        note = ask("    What happened? Type a note (or just Enter if it all worked): ")
        rec.mark("done", step=step["id"], note=note.strip(),
                 brave_playing=phone.brave_playing() if step.get("music") else None)
        print("    Saving the phone's state…")
        rec.snapshot(step["id"])
        rec.clock(step["id"])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["check", "record", "restore", "probe"])
    ap.add_argument("--serial", help="the phone's adb serial (default: its USB serial)")
    ap.add_argument("--steps", default="baseline", choices=sorted(STEP_SETS))
    ap.add_argument("--modes", default="vr,call,vr", help="probe: the link modes to test, in order")
    ap.add_argument("--seconds", type=int, default=8, help="probe: seconds per test")
    args = ap.parse_args()
    serial = args.serial or usb_serial()

    if args.command == "restore":
        done = restore(Phone(serial) if serial else None)
        print("Restored: " + (", ".join(done) if done else "nothing was pending"))
        return 0
    if args.command == "check":
        print(json.dumps(check(serial), indent=2))
        return 0
    if args.command == "probe":
        if not serial:
            print("No phone on USB.")
            return 1
        run_probes(Phone(serial), [m.strip() for m in args.modes.split(",") if m.strip()], args.seconds)
        return 0

    if not serial:
        print("No phone on USB: plug the cable in and allow USB debugging on the phone.")
        return 1
    source = snowball_source()
    if not source:
        print("The Blue Snowball isn't connected (no Snowball source in `pactl list sources short`).")
        return 1
    phone = Phone(serial)
    if pending():
        print("Undoing the settings an earlier run left: " + ", ".join(restore(phone)))
    helmet = phone.helmet()
    if not helmet["sena"]:
        print(f"Warning: the Sena isn't the active headset (active: {helmet['active'] or 'none'}). Turn the helmet on.")
        ask("Press Enter to go on anyway, or Ctrl-C to stop. ")

    out = BASE / datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out.mkdir(parents=True)
    steps = STEP_SETS[args.steps]
    (out / "steps.json").write_text(json.dumps({"serial": serial, "source": source, "steps": steps}, indent=1))
    note_pending(serial=serial, log_size=log_size(phone), battery=True)
    sh(["adb", "-s", serial, "logcat", "-G", TEST_LOG_SIZE])
    phone.shell("dumpsys battery unplug")
    rec = Recording(phone, source, out)
    print(f"Recording into {out}")
    print(SETUP.get(args.steps, SETUP["baseline"]))
    rec.start()
    time.sleep(1.5)
    if not rec.watcher.ok:
        print("Note: couldn't attach to Ray's session daemon; server timing will come from its journal only.")
    try:
        run_steps(phone, rec, steps)
        print("\nAll steps done.")
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        print("Stopping the recording and putting the phone back as it was…")
        rec.stop()
        done = restore(phone)
        print("Restored: " + (", ".join(done) if done else "nothing"))
        print(f"Saved in {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
