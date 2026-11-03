#!/usr/bin/env python3
"""pc_music_mcp.py - Ray plays music on the PC (the server computer's speakers), like phone_play_music on the phone.

YouTube Music runs in Ray's own Brave profile (a separate window, signed in once; ~/.local/share/dl-ai/brave-music):
Brave 136+ lets no program drive the tabs of the user's normal profile, a separate profile it does, on 127.0.0.1
only.  A song opens in a new tab and the old ones close, so there is one tab; the profile is started with autoplay
allowed, so it plays at once.  Pause, next and previous go through the desktop's media keys interface (MPRIS).

1. pc_play_music - find a song on YouTube Music (phone_mcp.find_song) and play it; no query: the Liked songs
2. pc_control_media - play, pause, next, previous
3. pc_get_now_playing - what the PC plays
"""
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from phone_mcp import SHORT_ANSWER, find_song  # noqa: E402

PROFILE = Path(os.environ.get("PC_MUSIC_PROFILE") or Path.home() / ".local/share/dl-ai/brave-music")
PORT = int(os.environ.get("PC_MUSIC_PORT") or 9333)
CDP = f"http://127.0.0.1:{PORT}"
YTM = "https://music.youtube.com/"
# the desktop site sends watch?list=LM (the phone's link) to its home page; the playlist page has a Play button
LIKED_PAGE = "https://music.youtube.com/playlist?list=LM"
PRESS_LIKED = ("(() => { const b = document.querySelector('ytmusic-responsive-header-renderer "
               "ytmusic-play-button-renderer'); if (!b) return false; b.click(); return true; })()")
WHERE = "on the PC (the server computer's speakers)"
WHEN = ("Use it when the message was sent from the PC, or the user names the PC (computer, desktop, računalo, "
        "kompjuter); when it was sent from the phone, the phone_ tools are for that, unless the user names the PC.")

TOOLS_DEFINITIONS = [
    {
        "name": "pc_play_music",
        "description": f"Find a song (or artist, album) on YouTube Music and play it {WHERE}. Without a query it plays "
                       f"the user's Liked songs (their default). {WHEN} For pause, skip or back, use pc_control_media.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string",
                          "description": "What to play, e.g. 'Bohemian Rhapsody Queen'. Leave it out for the Liked songs."},
                "url": {"type": "string",
                        "description": "A music.youtube.com or youtube.com link to play instead of searching (optional)."},
            },
        },
    },
    {
        "name": "pc_control_media",
        "description": f"Control what plays {WHERE}: play (resume), pause, next song, previous song. {WHEN}",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["play", "pause", "play_pause", "next", "previous"],
                           "description": "What to do."},
            },
            "required": ["action"],
        },
    },
    {
        "name": "pc_get_now_playing",
        "description": f"What plays {WHERE}: the song, the artist, and whether it plays or is paused. {WHEN}",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def brave_binary() -> Optional[str]:
    for name in (os.environ.get("PC_MUSIC_BRAVE"), "/opt/brave-origin-bin/brave-origin", "brave", "brave-browser"):
        if name and (shutil.which(name) or Path(name).is_file()):
            return shutil.which(name) or name
    return None


def _cdp(path: str, method: str = "GET", timeout: float = 3.0) -> Any:
    req = urllib.request.Request(CDP + path, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode() or "null"
    try:
        return json.loads(body)
    except ValueError:
        return body


def running() -> bool:
    try:
        return bool(_cdp("/json/version", timeout=1.0))
    except Exception:
        return False


def launch(url: str) -> Optional[str]:
    """Ray's Brave profile with [url]; None when it is up, else what went wrong."""
    binary = brave_binary()
    if not binary:
        return "Error: Brave is not installed on the PC."
    PROFILE.mkdir(parents=True, exist_ok=True)
    if not (os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY")):
        return ("Error: the PC music server has no display (WAYLAND_DISPLAY/DISPLAY); its mcp.json entry needs them "
                "in env_inherit.")
    # its own systemd scope: a restart of the session daemon (whose cgroup started it) doesn't close the window
    scope = ["systemd-run", "--user", "--scope", "--quiet", "--unit", f"ray-music-brave-{os.getpid()}"] \
        if shutil.which("systemd-run") else []
    subprocess.Popen(scope + [binary, f"--user-data-dir={PROFILE}", f"--remote-debugging-port={PORT}",
                      "--no-first-run", "--no-default-browser-check",
                      "--autoplay-policy=no-user-gesture-required", url],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
    end = time.time() + 20
    while time.time() < end:
        if running():
            return None
        time.sleep(0.5)
    return "Error: Ray's Brave window on the PC did not start."


def open_one_tab(url: str) -> Optional[str]:
    """[url] in Ray's profile, in a new tab; every other tab closes (one tab, the song)."""
    if not running():
        return launch(url)
    try:
        new = _cdp("/json/new?" + urllib.request.quote(url, safe=":/?=&"), method="PUT")
        for tab in _cdp("/json/list") or []:
            if tab.get("type") == "page" and tab.get("id") != (new or {}).get("id"):
                _cdp(f"/json/close/{tab['id']}")
    except Exception as e:
        return f"Error: Ray's Brave window on the PC did not answer ({e})."
    return None


def page_eval(expression: str) -> Any:
    """Runs [expression] in the one tab of Ray's profile (the DevTools protocol over its websocket)."""
    from websockets.sync.client import connect           # only here: the rest works without it
    tab = next(t for t in _cdp("/json/list") if t.get("type") == "page")
    with connect(tab["webSocketDebuggerUrl"], max_size=None, open_timeout=5) as ws:
        ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                            "params": {"expression": expression, "returnByValue": True}}))
        while True:
            msg = json.loads(ws.recv(timeout=5))
            if msg.get("id") == 1:
                return ((msg.get("result") or {}).get("result") or {}).get("value")


def ray_playing() -> bool:
    player = target_player()
    return bool(player) and "'Playing'" in _prop(player, "PlaybackStatus")


def make_it_play(liked: bool, wait_s: float = 15.0) -> bool:
    """The song (or the Liked songs) playing within [wait_s]: the playlist page's Play button is pressed; a song
    that loaded but waits (the first start of the profile) gets Play through the media keys."""
    end, pressed = time.time() + wait_s, False
    while time.time() < end:
        time.sleep(1)
        if ray_playing():
            return True
        try:
            if liked and not pressed:
                pressed = bool(page_eval(PRESS_LIKED))
            elif not liked and time.time() > end - wait_s / 2:
                player = target_player()
                if player and ray_profile_pid() and player.endswith(f".instance{ray_profile_pid()}"):
                    _gdbus(["-d", player, "-o", "/org/mpris/MediaPlayer2", "-m", "org.mpris.MediaPlayer2.Player.Play"])
        except Exception:
            pass                                          # the page is still loading: next second
    return ray_playing()


# ------------------------------------------------------------------------------------------ MPRIS (media keys)
def _gdbus(args: List[str], timeout: float = 3.0) -> Optional[str]:
    try:
        r = subprocess.run(["gdbus", "call", "--session"] + args, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip() if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def players() -> List[str]:
    try:
        r = subprocess.run(["busctl", "--user", "list", "--no-legend"], capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        return []
    return [ln.split()[0] for ln in r.stdout.splitlines() if ln.startswith("org.mpris.MediaPlayer2.")]


def _prop(player: str, name: str) -> str:
    return _gdbus(["-d", player, "-o", "/org/mpris/MediaPlayer2", "-m", "org.freedesktop.DBus.Properties.Get",
                   "org.mpris.MediaPlayer2.Player", name]) or ""


def ray_profile_pid() -> Optional[int]:
    """The browser process of Ray's profile (the one without --type=)."""
    try:
        r = subprocess.run(["pgrep", "-f", "--", f"--user-data-dir={PROFILE}"], capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        return None
    for pid in r.stdout.split():
        try:
            cmd = Path(f"/proc/{pid}/cmdline").read_bytes()    # the brave wrapper's exec -a: may be one string
        except OSError:
            continue
        if b"--type=" not in cmd and cmd.split(b" ")[0].split(b"\0")[0].endswith(b"/brave"):
            return int(pid)
    return None


def target_player() -> Optional[str]:
    """Ray's profile's player, else whatever plays on the PC, else a browser player."""
    found = players()
    pid = ray_profile_pid()
    if pid:
        own = [p for p in found if p.endswith(f".instance{pid}")]
        if own:
            return own[0]
    playing = [p for p in found if "'Playing'" in _prop(p, "PlaybackStatus")]
    if playing:
        return playing[0]
    browsers = [p for p in found if ".brave." in p or ".chromium." in p]
    return browsers[0] if browsers else None


def _meta(player: str, key: str) -> str:
    raw = _prop(player, "Metadata")
    i = raw.find(f"'{key}': <")
    if i < 0:
        return ""
    rest = raw[i + len(key) + 5:]
    rest = rest[1:] if rest.startswith("[") else rest
    q = rest[0] if rest[:1] in ("'", '"') else ""
    return rest[1:rest.index(q, 1)] if q and q in rest[1:] else ""


# ------------------------------------------------------------------------------------------ the tools
def play_music(args: Dict[str, Any]) -> str:
    url = str(args.get("url") or "").strip()
    query = str(args.get("query") or "").strip()
    if url:
        if not url.startswith(("https://music.youtube.com/", "https://www.youtube.com/", "https://youtu.be/")):
            return "Error: only music.youtube.com or youtube.com links can be played."
        said = "Playing it on the PC."
    elif query:
        try:
            song = find_song(query)
        except Exception as e:
            return f"Error: YouTube Music could not be searched ({e})."
        if not song:
            return f"Error: YouTube Music found no song for '{query}'."
        url = f"https://music.youtube.com/watch?v={song['video_id']}"
        said = f"Playing '{song['title']}' by {song['artist']} on the PC."
    else:
        url, said = LIKED_PAGE, "Playing the Liked songs on the PC."
    err = open_one_tab(url)
    if err:
        return err
    if not make_it_play(liked=url == LIKED_PAGE):
        return ("Error: YouTube Music opened on the PC but didn't start. If it shows 'Sign in', the user must sign in "
                "once in Ray's music window on the PC.")
    return f"{said} {SHORT_ANSWER}"


ACTIONS = {"play": "Play", "pause": "Pause", "play_pause": "PlayPause", "next": "Next", "previous": "Previous"}
DONE = {"play": "Playing", "pause": "Paused", "play_pause": "Done", "next": "Skipped to the next song",
        "previous": "Back to the previous song"}


def control_media(args: Dict[str, Any]) -> str:
    action = str(args.get("action") or "play_pause").lower()
    if action not in ACTIONS:
        return f"Error: unknown action '{action}'."
    player = target_player()
    if not player:
        return ("Nothing is playing or paused on the PC. To start music, use pc_play_music (without a query it plays "
                "the Liked songs).")
    if _gdbus(["-d", player, "-o", "/org/mpris/MediaPlayer2", "-m", f"org.mpris.MediaPlayer2.Player.{ACTIONS[action]}"]) is None:
        return "Error: the PC's player did not answer."
    return f"{DONE[action]} on the PC. {SHORT_ANSWER}"


def now_playing(args: Dict[str, Any]) -> str:
    player = target_player()
    if not player:
        return "Nothing is playing on the PC."
    status = "Playing" if "'Playing'" in _prop(player, "PlaybackStatus") else "Paused"
    title = _meta(player, "xesam:title").removesuffix(" | YouTube Music") or "an unknown song"
    artist = _meta(player, "xesam:artist")
    return f"{status} on the PC: '{title}'" + (f" by {artist}" if artist else "") + "."


RUN = {"pc_play_music": play_music, "pc_control_media": control_media, "pc_get_now_playing": now_playing}


def handle(req: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    mid, method = req.get("id"), req.get("method")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
            "serverInfo": {"name": "ray-pc-music-mcp", "version": "1.0.0"}}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS_DEFINITIONS}}
    if method == "tools/call":
        params = req.get("params") or {}
        run = RUN.get(params.get("name", ""))
        text = run(params.get("arguments") or {}) if run else f"Unknown tool: '{params.get('name')}'"
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "isError": text.startswith(("Error", "Unknown")), "content": [{"type": "text", "text": text}]}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if mid is None:                                   # a notification (notifications/initialized): no answer
        return None
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Method '{method}' not found"}}


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            continue
        res = handle(req)
        if res is not None:
            sys.stdout.write(json.dumps(res) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
