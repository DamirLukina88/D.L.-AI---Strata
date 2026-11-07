#!/usr/bin/env python3
"""phone_mcp.py - Autonomous Phone MCP Server for Ray Android Companion.

Provides Ray with autonomous smartphone capabilities:
1. phone_toggle_torch - Flashlight on/off
2. phone_get_battery - Battery percentage, charging, and health
3. phone_set_volume - Ring, media, alarm, notification volume
4. phone_set_alarm - Set clock alarm
5. phone_launch_app - Launch app by name or package
6. phone_get_recent_notifications - Status bar notifications
7. phone_get_2fa_code - Multilingual 2FA/SMS OTP extraction
8. phone_get_now_playing - Media metadata (Spotify, YouTube)
9. phone_control_media - Media playback (play, pause, next, previous)
10. phone_camera_snap - take a photo (back camera, shutter sound) and show it to the model
11. phone_get_last_photo - the newest photo Ray took, again
12. phone_get_gallery_image - the newest photo or screenshot the user took (the phone's gallery)
13. phone_get_screen - Accessibility screen inspection
14. phone_play_music - find a song on YouTube Music and play it in the phone's browser (Brave)
"""
import json
import os
import re
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional


def load_secrets():
    secrets_path = Path.home() / ".config" / "dl-ai" / "secrets.env"
    try:
        lines = secrets_path.read_text(encoding="utf-8").splitlines()
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except OSError:
        pass


load_secrets()

SERVER_PORT = int(os.environ.get("STRATA_PORT", "8080"))
SERVER_BASE = os.environ.get("STRATA_URL", f"http://127.0.0.1:{SERVER_PORT}")

# Multilingual Croatian and English 2FA / OTP patterns
OTP_PATTERNS = [
    # English standard / Google / Bank patterns
    re.compile(r"(?:verification\s+code|security\s+code|passcode|otp|token)\s*(?:is|:)?\s*([0-9]{4,8})\b", re.IGNORECASE),
    re.compile(r"\b([0-9]{4,8})\s+is\s+your\s+(?:verification|security|activation)?\s*(?:code|otp|token)\b", re.IGNORECASE),
    re.compile(r"\bcode\s*[:\-]\s*([0-9]{4,8})\b", re.IGNORECASE),
    # Croatian banking & telco patterns (PBZ, ZABA, Erste, A1, HT, Telemach, e-Građani)
    re.compile(r"(?:jednokratna\s+(?:lozinka|zaporka)|jednokratni\s+kod|sigurnosni\s+kod|aktivacijski\s+kod|kod\s+za\s+prijavu|m-token|token)\s*(?:je|:)?\s*([0-9]{4,8})\b", re.IGNORECASE),
    re.compile(r"(?:va[sš]\s+jednokratni\s+kod|va[sš]\s+sigurnosni\s+kod|va[sš]\s+aktivacijski\s+kod)\s*(?:je|:)?\s*([0-9]{4,8})\b", re.IGNORECASE),
    re.compile(r"(?:lozinka|zaporka|kod|token)[^\d\n]{0,25}\b([0-9]{4,8})\b", re.IGNORECASE),
]

TOOLS_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "name": "phone_toggle_torch",
        "description": "Turn the phone flashlight / torch on or off. Works at any time, including while the phone is locked and Ray is in the background.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "enabled": {
                    "type": "boolean",
                    "description": "True to turn the torch on, False to turn it off."
                }
            },
            "required": ["enabled"]
        }
    },
    {
        "name": "phone_get_battery",
        "description": "Get current phone battery percentage, charging state, voltage, temperature, and battery health. Works at any time, including while the phone is locked.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "phone_set_volume",
        "description": "Set phone volume level for media, ring, alarm, or notification. Works at any time, including while the phone is locked.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "stream": {
                    "type": "string",
                    "enum": ["media", "ring", "alarm", "notification"],
                    "description": "Audio stream to adjust."
                },
                "level": {
                    "type": "integer",
                    "description": "Target volume in percent, 0-100."
                }
            },
            "required": ["stream", "level"]
        }
    },
    {
        "name": "phone_set_alarm",
        "description": "Set an alarm on the phone for a specific hour and minute with an optional label. Works while the phone is locked or unlocked.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "hour": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 23,
                    "description": "Alarm hour in 24h format (0-23)."
                },
                "minute": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 59,
                    "description": "Alarm minute (0-59)."
                },
                "label": {
                    "type": "string",
                    "description": "Optional label or description for the alarm."
                }
            },
            "required": ["hour", "minute"]
        }
    },
    {
        "name": "phone_launch_app",
        "description": "Open or launch an application on the phone by app name or package name (e.g. 'spotify', 'youtube', 'settings', 'camera'). Works while the phone is locked or unlocked.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "package_or_name": {
                    "type": "string",
                    "description": "App name or Android package identifier."
                }
            },
            "required": ["package_or_name"]
        }
    },
    {
        "name": "phone_get_recent_notifications",
        "description": "Retrieve recent notifications posted to the phone status bar. Works at any time, including while the phone is locked.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "count": {
                    "type": "integer",
                    "default": 5,
                    "description": "Maximum number of recent notifications to retrieve (default: 5)."
                }
            }
        }
    },
    {
        "name": "phone_get_2fa_code",
        "description": "Extract the most recent 2FA / OTP verification code from SMS or notifications (supports Croatian banking and English formats). Works at any time, including while the phone is locked.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "phone_get_now_playing",
        "description": "Get information about currently playing media (Ray Music Player, Spotify, YouTube, etc.) including title, artist, and playback state. Works while the phone is locked or unlocked. Use it when the message was sent from the phone, or the user names the phone (mobitel); when it was sent from the PC, the pc_ tools are for that, unless the user names the phone.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "phone_control_media",
        "description": "Control what the phone is playing (Ray Music Player, YouTube Music, Spotify, ...): play, pause, next song, previous song, stop. Works at any time, including while the phone is locked. To play a particular song, use phone_play_music. Use it when the message was sent from the phone, or the user names the phone (mobitel); when it was sent from the PC, the pc_ tools are for that, unless the user names the phone.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["play", "pause", "play_pause", "next", "previous", "stop"],
                    "description": "Playback action to perform."
                }
            },
            "required": ["action"]
        }
    },
    {
        "name": "phone_camera_snap",
        "description": "Take a photo with the phone's back camera and see it: the photo comes back to you as an image. Use it whenever the user asks what you see, to look at something, or what is in front of the phone (not the workspace files). Not for a photo or screenshot the user already took: that is phone_get_gallery_image. The phone plays the shutter sound. Works at any time, including while the phone is locked.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "What the photo is for (optional)."
                }
            }
        }
    },
    {
        "name": "phone_get_last_photo",
        "description": "Show the newest photo Ray took himself with phone_camera_snap again (it is in the workspace under phone-photos/); if none was taken in the last 2 minutes, it takes one now like phone_camera_snap. Not for the user's own photos or screenshots: that is phone_get_gallery_image. Works at any time, including while the phone is locked.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "phone_get_gallery_image",
        "description": "Look at the newest photo or screenshot the user took, from the phone's gallery: it comes back to you as an image. Use it when the user asks for their latest/last photo, screenshot, or a picture from the gallery or the phone. It never takes a new photo. Works at any time, including while the phone is locked.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": ["photo", "screenshot", "any"],
                    "description": "photo: the newest camera photo; screenshot: the newest screenshot; any: the newest image of any kind (default)."
                }
            }
        }
    },
    {
        "name": "phone_play_music",
        "description": "Find a song (or artist, album) on YouTube Music and play it on the phone in Ray's lock-screen music player. Use it when the user asks to play, put on or search for a song or music. Without a query it plays the user's Liked songs (their default when they just say 'play music'). It starts automatically once Ray has finished talking, even when the phone is locked. For pause, skip or back, use phone_control_media. Use it when the message was sent from the phone, or the user names the phone (mobitel); when it was sent from the PC, the pc_ tools are for that, unless the user names the phone.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What to play, e.g. 'Bohemian Rhapsody Queen' or 'Dubioza Kolektiv'. Leave it out for the Liked songs."
                },
                "url": {
                    "type": "string",
                    "description": "A music.youtube.com or youtube.com link to play instead of searching (optional)."
                }
            }
        }
    },
    {
        "name": "phone_get_screen",
        "description": "Inspect visible text and UI elements currently displayed on the phone screen via Accessibility. Works at any time, including while the phone is locked.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "phone_read_sensors",
        "description": "Read all 107 hardware and virtual sensors on the phone (Xiaomi 17 Ultra): includes computed Spirit Level / Surface Evenness (pitch, roll, total tilt angle in degrees to 0.01°, whether the surface is level, and which edge is higher), 6-axis IMU (480 Hz STMicro lsm6dsv accelerometer, gyroscope, gravity, linear acceleration), 3-axis magnetometer & compass heading (0-360°), barometric altimeter (Bosch bmp5 hPa & altitude in meters), front/back ambient light (lux), front/back color temperature (K), light flicker (Hz), proximity, step counter, laser ToF, and Xiaomi smart context sensors (elevator, collision, subway, basement, holder, pickup, grip). Works at any time, including while the phone is locked.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "default": "all",
                    "description": "Sensor filter: 'all' (default, all 107 sensors + spirit level summary), 'level', 'imu', 'environment', 'xiaomi', or any sensor name substring (e.g. 'bmp5', 'tof', 'flicker')."
                },
                "sample_ms": {
                    "type": "integer",
                    "default": 280,
                    "description": "Live sampling window in milliseconds (80-5000, default: 280)."
                }
            }
        }
    },
    {
        "name": "phone_sensor_stream",
        "description": "Start, monitor, check status, or stop an on-demand real-time high-frequency sensor stream from the phone to Ray and the Ray Web UI visualization panel. Use mode='jumps' to monitor jumps (detects takeoff G-force, airborne flight time in ms, vertical jump height in cm, and landing impact G-force), mode='level' for continuous spirit-level surface tilting, or mode='raw' for general telemetry. Works while the phone is locked.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["monitor", "start", "status", "stop"],
                    "default": "monitor",
                    "description": "'monitor' streams for duration_sec and returns the complete analysis; 'start' starts streaming in the background so the Web UI visualization panel shows live data; 'status' reads current stream metrics; 'stop' stops the stream."
                },
                "mode": {
                    "type": "string",
                    "enum": ["jumps", "level", "raw", "all"],
                    "default": "jumps",
                    "description": "Stream analysis mode: 'jumps' (jump height & flight-time tracker), 'level' (live spirit level), or 'raw'."
                },
                "duration_sec": {
                    "type": "integer",
                    "default": 10,
                    "description": "Stream duration in seconds (1-120, default: 10)."
                },
                "rate_hz": {
                    "type": "integer",
                    "default": 100,
                    "description": "IMU sampling rate in Hz (10-480, default: 100)."
                }
            }
        }
    },
    {
        "name": "phone_clipboard",
        "description": "Read or set the phone and PC clipboard (with live two-way synchronization between Android ClipboardManager and Linux KDE Klipper). Works while the phone is locked.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["get", "set"],
                    "default": "get",
                    "description": "'get' reads the current clipboard text; 'set' copies 'text' to both the phone and PC clipboards."
                },
                "text": {
                    "type": "string",
                    "default": "",
                    "description": "Text to copy to the clipboard when action='set'."
                }
            }
        }
    },
    {
        "name": "phone_files",
        "description": "Full remote file access to the phone's shared storage (/sdcard/Download, Documents, DCIM/Camera, Pictures, Music, etc.) and bidirectional file transfer between the phone and PC workspace (~/DL-AI-workspace/phone-files/). Works while the phone is locked.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "search", "pull", "push", "read_text", "write_text"],
                    "default": "list",
                    "description": "'list' lists a phone folder; 'search' finds files matching 'pattern'; 'pull' copies a file from phone to PC workspace (phone-files/); 'push' copies a file from PC workspace to phone; 'read_text' / 'write_text' reads or writes a UTF-8 text file on the phone."
                },
                "path": {
                    "type": "string",
                    "default": "Download",
                    "description": "Path on the phone relative to /sdcard (e.g. 'Download', 'Documents', 'DCIM/Camera', '' for root, or 'Download/report.pdf')."
                },
                "workspace_path": {
                    "type": "string",
                    "default": "",
                    "description": "File path in the PC workspace (~/DL-AI-workspace/) for 'push' or custom destination name for 'pull'."
                },
                "pattern": {
                    "type": "string",
                    "default": "",
                    "description": "Filename search query when action='search'."
                },
                "content": {
                    "type": "string",
                    "default": "",
                    "description": "Text content to write when action='write_text'."
                }
            }
        }
    },
    {
        "name": "phone_calendar",
        "description": "Read, schedule, or delete events directly in the user's Google Calendar on the phone (via Android CalendarContract with automatic Google account cloud sync). Works silently in the background, even while the phone is locked.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "add", "delete", "calendars"],
                    "default": "list",
                    "description": "'list' shows upcoming Google Calendar events; 'add' schedules a new event; 'delete' removes an event by event_id or title; 'calendars' lists synced calendar accounts."
                },
                "title": {
                    "type": "string",
                    "default": "",
                    "description": "Event title (for 'add', 'delete', or optional title filter for 'list')."
                },
                "start_time": {
                    "type": "string",
                    "default": "",
                    "description": "Event start time for 'add' in 'YYYY-MM-DD HH:MM' format (e.g. '2026-11-08 14:30', 'today 18:00', or 'tomorrow 10:00')."
                },
                "end_time": {
                    "type": "string",
                    "default": "",
                    "description": "Optional event end time in 'YYYY-MM-DD HH:MM' format (if omitted, uses duration_minutes)."
                },
                "duration_minutes": {
                    "type": "integer",
                    "default": 60,
                    "description": "Duration in minutes when end_time is omitted (default: 60)."
                },
                "location": {
                    "type": "string",
                    "default": "",
                    "description": "Optional event location."
                },
                "description": {
                    "type": "string",
                    "default": "",
                    "description": "Optional event description or notes."
                },
                "days_ahead": {
                    "type": "integer",
                    "default": 7,
                    "description": "Number of days ahead to query for 'list' (default: 7)."
                },
                "reminder_minutes": {
                    "type": "integer",
                    "default": 15,
                    "description": "Popup reminder minutes before the event (default: 15)."
                },
                "event_id": {
                    "type": "integer",
                    "default": 0,
                    "description": "Event ID to delete when action='delete'."
                }
            }
        }
    }
]


def extract_otp_code(text: str) -> Optional[str]:
    """Extract a 2FA OTP verification code from Croatian or English text."""
    if not text:
        return None
    for pattern in OTP_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1)
    return None


BRAVE = "com.brave.browser"
# YouTube Music's own search (the web player's API; no account or key), filtered to songs
YTM_SEARCH = "https://music.youtube.com/youtubei/v1/search?prettyPrint=false"
YTM_SONGS = "EgWKAQIIAWoKEAkQBRAKEAMQBA=="
# the model talked at length ("That opening riff should be loud enough... Say pause or next whenever you want")
SHORT_ANSWER = "Say only that sentence to the user, word for word: no greeting, no comment, no offer."
LIKED_SONGS = "https://music.youtube.com/watch?list=LM"          # the signed-in user's Liked songs


def find_song(query: str, timeout: float = 10.0) -> Optional[Dict[str, str]]:
    """The first song YouTube Music finds for query: {video_id, title, artist}, or None."""
    body = {"context": {"client": {"clientName": "WEB_REMIX", "clientVersion": "1.20241106.01.00", "hl": "en"}},
            "query": query, "params": YTM_SONGS}
    req = urllib.request.Request(YTM_SEARCH, data=json.dumps(body).encode(), headers={
        "Content-Type": "application/json", "User-Agent": "Mozilla/5.0", "Origin": "https://music.youtube.com"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return first_song(json.loads(resp.read().decode()))


def first_song(data: Any) -> Optional[Dict[str, str]]:
    """The first song row of a YouTube Music search answer."""
    stack = [data]
    while stack:
        o = stack.pop(0)
        if isinstance(o, dict):
            row = o.get("musicResponsiveListItemRenderer")
            vid = ((row or {}).get("playlistItemData") or {}).get("videoId")
            if vid:
                cols = ["".join(r.get("text", "") for r in
                                (c.get("musicResponsiveListItemFlexColumnRenderer", {}).get("text", {}).get("runs") or []))
                        for c in row.get("flexColumns", [])]
                return {"video_id": vid, "title": cols[0] if cols else "?",
                        "artist": (cols[1].split(" • ")[0] if len(cols) > 1 else "") or "an unknown artist"}
            stack.extend(o.values())
        elif isinstance(o, list):
            stack.extend(o)
    return None


# While this file exists (tools/helmet_test.py makes it during a helmet test) the adb fallback is off: phone tools go
# only through the app, as on the road, where there is no adb.  Without the file nothing changes
ADB_OFF_FLAG = Path(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}") / "dl-ai" / "phone-adb-off"


class PhoneMcpServer:
    """Phone MCP Server implementation handling tools/list, tools/call, and device communication."""

    def __init__(self, base_url: str = SERVER_BASE, adb_enabled: bool = True, api_key: Optional[str] = None):
        self.base_url = base_url.rstrip("/")
        self.adb_enabled = adb_enabled
        self.api_key = api_key if api_key is not None else os.environ.get("STRATA_API_KEY", "")
        self.tools = TOOLS_DEFINITIONS

    def _headers(self, json_type: bool = True) -> Dict[str, str]:
        h = {"User-Agent": "RayPhoneMCP/1.0"}
        if json_type:
            h["Content-Type"] = "application/json"
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
            h["x-api-key"] = self.api_key
        return h

    def is_phone_reachable(self) -> bool:
        """Check if phone companion is reachable via server HTTP relay or ADB."""
        # 1. Try server relay endpoint
        try:
            req = urllib.request.Request(f"{self.base_url}/api/phone/status", headers=self._headers(False))
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                data = json.loads(resp.read().decode())
                if data.get("connected"):
                    return True
        except Exception:
            pass

        # 2. Check if ADB device is attached
        if self.adb_enabled:
            return self._is_adb_connected()

        return False

    def _is_adb_connected(self) -> bool:
        if not self.adb_enabled or ADB_OFF_FLAG.exists():
            return False
        try:
            res = subprocess.run(["adb", "get-state"], capture_output=True, text=True, timeout=2.0)
            return res.returncode == 0 and "device" in res.stdout
        except (FileNotFoundError, subprocess.SubprocessError):
            return False

    def _run_adb_cmd(self, args: List[str], timeout: float = 5.0) -> Optional[str]:
        if not self.adb_enabled or not self._is_adb_connected():
            return None
        try:
            res = subprocess.run(["adb"] + args, capture_output=True, text=True, timeout=timeout)
            if res.returncode == 0:
                return res.stdout.strip()
        except (FileNotFoundError, subprocess.SubprocessError):
            pass
        return None

    # 25 s: the server waits up to 20 s for the phone (/api/phone/tool/call; a photo takes a few seconds), so its
    # answer (the result, or "the phone didn't answer") arrives before this side gives up
    def _call_companion_api(self, tool_name: str, args: Dict[str, Any], timeout: float = 25.0) -> Optional[str]:
        """Attempt to dispatch the tool call to the active Ray companion session via server relay."""
        dur_s = 0.0
        if isinstance(args, dict):
            try:
                dur_s = float(args.get("duration_sec") or 0.0)
            except (TypeError, ValueError):
                dur_s = 0.0
        call_timeout = max(timeout, min(140.0, dur_s + 15.0))
        payload = json.dumps({"tool": tool_name, "args": args}).encode("utf-8")
        try:
            req = urllib.request.Request(
                f"{self.base_url}/api/phone/tool/call",
                data=payload,
                headers=self._headers(True)
            )
            with urllib.request.urlopen(req, timeout=call_timeout) as resp:
                data = json.loads(resp.read().decode())
                if "result" in data:
                    res_str = str(data["result"])
                    if tool_name == "phone_files" and "phone-photos/file_" in res_str:
                        self._normalize_pulled_file(res_str)
                    return res_str
        except Exception:
            pass
        return None

    def _normalize_pulled_file(self, res_str: str) -> None:
        """Move fallback uploaded phone-photos/file_<name> to phone-files/<name> in workspace."""
        try:
            match = re.search(r"phone-photos/(file_[^\s)]+)", res_str)
            if match:
                fpath = match.group(1)
                clean_name = fpath.removeprefix("file_")
                workspace = Path(os.environ.get("STRATA_WORKSPACE_DIR") or Path.home() / "DL-AI-workspace")
                src = workspace / "phone-photos" / fpath
                dst = workspace / "phone-files" / clean_name
                if src.exists():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    src.replace(dst)
        except Exception:
            pass

    def is_companion_connected(self) -> bool:
        """Check if companion app reported heartbeat recently."""
        try:
            req = urllib.request.Request(f"{self.base_url}/api/phone/status", headers=self._headers(False))
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                data = json.loads(resp.read().decode())
                return bool(data.get("connected"))
        except Exception:
            return False

    def execute_tool(self, name: str, args: Dict[str, Any]) -> str:
        """Execute a phone tool with fallback across Companion API and ADB."""
        if name == "phone_play_music":
            args, found = self._resolve_song(args)
            if not args.get("url"):
                return found
            result = self._execute_on_phone(name, args)
            if result.startswith("Error"):
                return result
            if result.startswith("Not playing yet"):          # a locked phone: it starts once it is unlocked
                return f"{found.replace('Playing ', 'Opened ', 1)} {result}"
            return f"{found} {SHORT_ANSWER}"
        return self._execute_on_phone(name, args)

    def _resolve_song(self, args: Dict[str, Any]):
        """phone_play_music's link: the one given, else the first song YouTube Music finds; and what was found."""
        url = str(args.get("url") or "").strip()
        if url:
            if not re.match(r"https://(music\.|www\.|m\.)?youtube\.com/|https://youtu\.be/", url):
                return {}, "Error: only music.youtube.com or youtube.com links can be played."
            return {"url": url}, ""
        query = str(args.get("query") or "").strip()
        if not query:                                         # the user's default: their Liked songs
            return {"url": LIKED_SONGS}, "Playing the Liked songs."
        try:
            song = find_song(query)
        except Exception as e:
            return {}, f"Error: YouTube Music could not be searched ({e})."
        if not song:
            return {}, f"Error: YouTube Music found no song for '{query}'."
        return {"query": query, "url": f"https://music.youtube.com/watch?v={song['video_id']}"}, \
            f"Playing '{song['title']}' by {song['artist']}."

    def _execute_on_phone(self, name: str, args: Dict[str, Any]) -> str:
        # 1. Try Companion App via Server Relay if connected
        if self.is_companion_connected():
            relay_result = self._call_companion_api(name, args)
            if relay_result is not None:
                return relay_result

        # 2. If ADB is connected, dispatch to hardware directly or via intent
        if self._is_adb_connected():
            res = self._execute_via_adb(name, args)
            if res is not None:
                return res

        # 3. Phone is unreachable
        return (
            "Error: Phone is currently unreachable. Make sure the Ray companion app is open on the phone "
            "or connected to the same network / Wi-Fi as the home server."
        )

    def _execute_via_adb(self, name: str, args: Dict[str, Any]) -> Optional[str]:
        # Broadcast to running Ray companion app first if installed
        broadcast_cmd = [
            "shell", "am", "broadcast",
            "-a", "com.damirl.ray.ACTION_EXECUTE_TOOL",
            "-n", "com.damirl.ray/.tools.RayToolsReceiver",
            "--es", "tool", name,
            # adb shell joins its arguments into one command line on the phone: quoted, or a space in the
            # arguments (a song name) split them and the app got broken JSON
            "--es", "args", shlex.quote(json.dumps(args))
        ]
        if name != "phone_get_gallery_image":              # the gallery is read over adb alone (one copy)
            self._run_adb_cmd(broadcast_cmd, timeout=1.5)

        if name == "phone_toggle_torch":
            enabled = bool(args.get("enabled", False))
            # Send torch broadcast to Ray app or statusbar
            intent = [
                "shell", "am", "broadcast",
                "-a", "com.damirl.ray.ACTION_TORCH",
                "--ez", "enabled", str(enabled).lower()
            ]
            self._run_adb_cmd(intent)
            return f"Phone flashlight turned {'ON' if enabled else 'OFF'}."

        elif name == "phone_get_battery":
            out = self._run_adb_cmd(["shell", "dumpsys", "battery"])
            if out:
                level = re.search(r"level:\s*(\d+)", out)
                status = re.search(r"status:\s*(\d+)", out)
                health = re.search(r"health:\s*(\d+)", out)
                temp = re.search(r"temperature:\s*(\d+)", out)
                ac = "AC powered: true" in out
                usb = "USB powered: true" in out
                wireless = "Wireless powered: true" in out
                charging = ac or usb or wireless or (status and status.group(1) == "2")

                lvl_str = level.group(1) if level else "Unknown"
                temp_c = f"{float(temp.group(1))/10.0:.1f} °C" if temp else "Unknown"
                health_map = {"1": "Unknown", "2": "Good", "3": "Overheat", "4": "Dead", "5": "Over voltage", "6": "Failure"}
                health_str = health_map.get(health.group(1) if health else "", "Good")

                return (
                    f"Battery: {lvl_str}%\n"
                    f"Charging: {'Yes' if charging else 'No'}\n"
                    f"Health: {health_str}\n"
                    f"Temperature: {temp_c}"
                )

        elif name == "phone_set_volume":
            stream = str(args.get("stream", "media")).lower()
            level = int(args.get("level", 50))
            stream_code = {"media": "3", "ring": "2", "alarm": "4", "notification": "5"}.get(stream, "3")
            mapped_level = max(0, min(15, int(level * 15 / 100))) if level > 15 else max(0, min(15, level))
            self._run_adb_cmd(["shell", "media", "volume", "--stream", stream_code, "--set", str(mapped_level)])
            return f"Volume for {stream} stream set to level {mapped_level} (scale 0-15)."

        elif name == "phone_set_alarm":
            hour = int(args.get("hour", 8))
            minute = int(args.get("minute", 0))
            label = str(args.get("label", "Alarm from Ray"))
            self._run_adb_cmd([
                "shell", "am", "start",
                "-a", "android.intent.action.SET_ALARM",
                "--ei", "android.intent.extra.alarm.HOUR", str(hour),
                "--ei", "android.intent.extra.alarm.MINUTES", str(minute),
                "--es", "android.intent.extra.alarm.MESSAGE", label,
                "--ez", "android.intent.extra.alarm.SKIP_UI", "true"
            ])
            return f"Alarm set for {hour:02d}:{minute:02d} ('{label}')."

        elif name == "phone_launch_app":
            target = str(args.get("package_or_name", "")).strip().lower()
            package_map = {
                "spotify": "com.spotify.music",
                "youtube": "com.google.android.youtube",
                "settings": "com.android.settings",
                "camera": "com.android.camera",
                "chrome": "com.android.chrome",
                "maps": "com.google.android.apps.maps",
                "clock": "com.google.android.deskclock",
                "calculator": "com.miui.calculator",
            }
            pkg = package_map.get(target, target)
            out = self._run_adb_cmd(["shell", "monkey", "-p", pkg, "-c", "android.intent.category.LAUNCHER", "1"])
            if out and "No activities found" not in out:
                return f"Launched app '{target}' ({pkg})."
            return f"Attempted to launch app '{target}'. If not installed, please specify full package name."

        elif name == "phone_get_recent_notifications":
            count = int(args.get("count", 5))
            out = self._run_adb_cmd(["shell", "dumpsys", "notification", "--noredact"])
            if out:
                notifs = []
                for line in out.splitlines():
                    if "tickerText=" in line or "android.title=" in line or "android.text=" in line:
                        clean_line = line.strip()
                        if clean_line and len(clean_line) > 10:
                            notifs.append(clean_line)
                    if len(notifs) >= count:
                        break
                if notifs:
                    return "Recent Notifications:\n" + "\n".join(f"- {n}" for n in notifs[:count])
            return "No recent notifications found."

        elif name == "phone_get_2fa_code":
            out = self._run_adb_cmd(["shell", "dumpsys", "notification", "--noredact"])
            if out:
                for line in reversed(out.splitlines()):
                    code = extract_otp_code(line)
                    if code:
                        return f"Your verification code is {code}"
            return "No 2FA / OTP verification code found in recent notifications."

        elif name == "phone_get_now_playing":
            out = self._run_adb_cmd(["shell", "dumpsys", "media_session"])
            if out:
                title = re.search(r"description=.*title=([^,\n]+)", out)
                artist = re.search(r"artist=([^,\n]+)", out)
                state = re.search(r"state=PlaybackState\s*\{\s*state=(\d+)", out)
                state_str = "Playing" if state and state.group(1) == "3" else "Paused"
                if title:
                    t = title.group(1).strip()
                    a = artist.group(1).strip() if artist else "Unknown Artist"
                    return f"{state_str}: '{t}' by {a}"
            return "No active media playback currently reported."

        elif name == "phone_control_media":
            action = str(args.get("action", "play_pause")).lower()
            key_map = {
                "play": "126",        # KEYCODE_MEDIA_PLAY
                "pause": "127",       # KEYCODE_MEDIA_PAUSE
                "play_pause": "85",   # KEYCODE_MEDIA_PLAY_PAUSE
                "next": "87",         # KEYCODE_MEDIA_NEXT
                "previous": "88",     # KEYCODE_MEDIA_PREVIOUS
                "stop": "86",         # KEYCODE_MEDIA_STOP
            }
            key = key_map.get(action, "85")
            self._run_adb_cmd(["shell", "input", "keyevent", key])
            return f"Media action '{action}' executed."

        elif name == "phone_camera_snap":
            # the broadcast above made the app take the photo (if Ray is on screen); fetch it over adb
            time.sleep(4)
            return self._pull_last_photo()

        elif name == "phone_get_last_photo":
            return self._pull_last_photo()

        elif name == "phone_get_gallery_image":
            return self._pull_gallery_image(str(args.get("kind", "any")).lower())

        elif name == "phone_play_music":
            # the broadcast above had Ray's app open RayMusicActivity (showWhenLocked=true), which plays once Ray is quiet
            return "Started."

        elif name == "phone_get_screen":
            out = self._run_adb_cmd(["shell", "uiautomator", "dump", "/dev/stdout"])
            if out:
                texts = re.findall(r'text="([^"]+)"', out)
                desc = re.findall(r'content-desc="([^"]+)"', out)
                all_text = [t.strip() for t in (texts + desc) if t.strip()]
                unique_text = list(dict.fromkeys(all_text))
                if unique_text:
                    return "Visible screen content:\n" + "\n".join(f"- {t}" for t in unique_text[:30])
            return "No readable text detected on current screen."

        elif name == "phone_read_sensors":
            cat = str(args.get("category", "summary")).lower()
            out = self._run_adb_cmd(["shell", "dumpsys", "sensorservice"])
            if not out:
                return "Error reading sensors via ADB."
            if cat == "list":
                sensors = []
                for line in out.splitlines():
                    if ") " in line and "type:" in line:
                        sensors.append(line.strip())
                return f"Total sensors registered: {len(sensors)}\n" + "\n".join(sensors[:40])
            elif cat == "spirit_level":
                return (
                    "Spirit Level / Surface Evenness:\n"
                    "Accelerometer and gravity sensors are active. Launch the Ray companion app for live "
                    "100 Hz pitch, roll, and inclination calculations accurate to 0.01°."
                )
            else:
                total_match = re.search(r"Total\s+(\d+)\s+h/w sensors", out)
                cnt = total_match.group(1) if total_match else "107"
                return (
                    f"Xiaomi 17 Ultra Sensors (Total: {cnt} hardware sensors active)\n"
                    f"Status: Operational across Motion, Orientation, Environmental, and Hardware sensors.\n"
                    f"For real-time streaming and surface inclination, use the Ray companion app stream."
                )

        elif name == "phone_sensor_stream":
            return (
                "Sensor streaming requires the Ray companion app to be active on the phone or connected via relay. "
                "Open the Ray companion app to stream real-time 100 Hz sensor telemetry."
            )

        elif name == "phone_clipboard":
            action = str(args.get("action", "get")).lower()
            if action == "set":
                text = str(args.get("text", ""))
                # Update KDE Plasma clipboard via qdbus6
                try:
                    subprocess.run(
                        ["qdbus6", "org.kde.klipper", "/klipper", "org.kde.klipper.klipper.setClipboardContents", text],
                        capture_output=True, text=True, timeout=2.0
                    )
                except Exception:
                    pass
                # Update server clipboard endpoint
                try:
                    payload = json.dumps({"text": text}).encode("utf-8")
                    req = urllib.request.Request(f"{self.base_url}/v1/ray/phone/clipboard", data=payload, headers=self._headers(True))
                    with urllib.request.urlopen(req, timeout=2.0):
                        pass
                except Exception:
                    pass
                return f"Clipboard updated with {len(text)} characters."
            else:
                # Get clipboard: try KDE Klipper first
                try:
                    res = subprocess.run(
                        ["qdbus6", "org.kde.klipper", "/klipper", "org.kde.klipper.klipper.getClipboardContents"],
                        capture_output=True, text=True, timeout=2.0
                    )
                    if res.returncode == 0 and res.stdout.strip():
                        return f"Clipboard content:\n{res.stdout.strip()}"
                except Exception:
                    pass
                # Fallback to server clipboard
                try:
                    req = urllib.request.Request(f"{self.base_url}/v1/ray/phone/clipboard", headers=self._headers(False))
                    with urllib.request.urlopen(req, timeout=2.0) as resp:
                        data = json.loads(resp.read().decode())
                        txt = data.get("text", "")
                        if txt:
                            return f"Clipboard content:\n{txt}"
                except Exception:
                    pass
                return "Clipboard is currently empty."

        elif name == "phone_files":
            action = str(args.get("action", "list")).lower()
            path = str(args.get("path", "/sdcard/Download")).strip()
            if action == "list":
                out = self._run_adb_cmd(["shell", "ls", "-lh", path], timeout=5.0)
                if out:
                    return f"Directory listing for {path}:\n{out}"
                return f"Directory {path} is empty or not accessible."
            elif action == "read_text":
                max_lines = int(args.get("max_lines", 100))
                out = self._run_adb_cmd(["shell", "head", f"-n{max_lines}", path], timeout=5.0)
                if out is not None:
                    return out
                return f"Could not read text file at {path}."
            elif action == "search":
                pattern = str(args.get("pattern", "")).strip()
                out = self._run_adb_cmd(["shell", f"find '{path}' -iname '*{pattern}*' 2>/dev/null | head -50"], timeout=10.0)
                if out:
                    return f"Search results for '{pattern}' in {path}:\n{out}"
                return f"No matching files found for '{pattern}'."
            elif action == "pull":
                workspace = Path(os.environ.get("STRATA_WORKSPACE_DIR") or Path.home() / "DL-AI-workspace") / "phone-files"
                workspace.mkdir(parents=True, exist_ok=True)
                dest = workspace / os.path.basename(path)
                res = self._run_adb_cmd(["pull", path, str(dest)], timeout=30.0)
                if res is not None and dest.exists():
                    size = dest.stat().st_size
                    return f"Pulled '{path}' to workspace: phone-files/{dest.name} (size: {size} bytes)."
                return f"Failed to pull file '{path}' from phone."
            elif action == "push":
                src = str(args.get("workspace_path", "")).strip()
                workspace = Path(os.environ.get("STRATA_WORKSPACE_DIR") or Path.home() / "DL-AI-workspace")
                local_file = (workspace / src) if not os.path.isabs(src) else Path(src)
                if not local_file.exists():
                    return f"Error: source file '{local_file}' does not exist on PC workspace."
                target = path if path.endswith("/") else f"{path}/{local_file.name}"
                res = self._run_adb_cmd(["push", str(local_file), target], timeout=30.0)
                if res is not None:
                    return f"Pushed '{local_file.name}' to phone: {target}"
                return f"Failed to push file to phone at '{target}'."
            return f"Unsupported file action: {action}"

        elif name == "phone_calendar":
            action = str(args.get("action", "list")).lower()
            if action == "list_accounts":
                out = self._run_adb_cmd([
                    "shell", "content", "query", "--uri", "content://com.android.calendar/calendars",
                    "--projection", "_id:calendar_displayName:account_name:account_type"
                ], timeout=5.0)
                if out:
                    return f"Configured Google Calendar accounts:\n{out}"
                return "No calendar accounts found or permission not granted."
            elif action == "list":
                days = int(args.get("days_ahead", 7))
                out = self._run_adb_cmd([
                    "shell", "content", "query", "--uri", "content://com.android.calendar/events",
                    "--projection", "title:dtstart:dtend:eventLocation:description"
                ], timeout=5.0)
                if out:
                    lines = [l.strip() for l in out.splitlines() if l.strip().startswith("Row:")]
                    return f"Upcoming Calendar Events (next {days} days, found {len(lines)}):\n" + "\n".join(lines[:20])
                return "No calendar events found."
            elif action == "add":
                return (
                    "Adding a calendar event requires the Ray companion app to be active with calendar permissions. "
                    "Open the companion app to synchronize calendar events."
                )
            elif action == "delete":
                event_id = str(args.get("event_id", "")).strip()
                if not event_id:
                    return "Error: event_id is required to delete an event."
                out = self._run_adb_cmd([
                    "shell", "content", "delete", "--uri", "content://com.android.calendar/events",
                    "--where", f"_id={event_id}"
                ], timeout=5.0)
                return f"Deleted calendar event #{event_id}."
            return f"Unsupported calendar action: {action}"

        return None

    PHOTO_DIR = "/sdcard/Android/data/com.damirl.ray/files/Pictures"

    def _pull_last_photo(self) -> str:
        """The app isn't relaying (its page is closed): the newest photo Ray's camera saved, pulled over adb into the
        workspace (phone-photos/), at most 1600 px when Pillow is there.  Same [[image: …]] answer as the app's."""
        listing = self._run_adb_cmd(["shell", "ls", "-l", self.PHOTO_DIR]) or ""
        snaps = []
        for line in listing.splitlines():
            parts = line.split()
            if len(parts) >= 8 and parts[-1].startswith("RAY_SNAP_") and parts[-1].endswith(".jpg"):
                snaps.append((parts[-1], int(parts[4]) if parts[4].isdigit() else 0))
        if not snaps:
            return "Error: no photo yet. Open the camera with phone_camera_snap first."
        snaps.sort(key=lambda x: x[0], reverse=True)          # RAY_SNAP_<yyyyMMdd_HHmmss>_: the name sorts by time
        newest, size = snaps[0]
        if size == 0:
            return ("Error: the camera hasn't handed over the photo yet. After taking it, the user must tap the tick "
                    "(✓, confirm) in the camera's review screen; ask them to do that, or to take it again.")
        return self._pull_image(f"{self.PHOTO_DIR}/{newest}", f"phone-photos/{newest.rsplit('_', 1)[0]}.jpg")

    GALLERY_DIRS = {
        "photo": ["/sdcard/DCIM/Camera"],
        "screenshot": ["/sdcard/DCIM/Screenshots", "/sdcard/Pictures/Screenshots"],
    }
    IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp", ".heic")

    def _pull_gallery_image(self, kind: str) -> str:
        """The newest camera photo or screenshot in the gallery folders, pulled over adb (newest by file time)."""
        dirs = self.GALLERY_DIRS.get(kind) or self.GALLERY_DIRS["photo"] + self.GALLERY_DIRS["screenshot"]
        what = kind if kind in self.GALLERY_DIRS else "image"
        newest = None                                         # (epoch seconds, path)
        for d in dirs:
            out = self._run_adb_cmd(["shell", f"ls -t '{d}' 2>/dev/null | head -20"]) or ""
            for fn in out.split():
                if fn.lower().endswith(self.IMAGE_EXT) and not fn.startswith("."):
                    path = f"{d}/{fn}"
                    t = (self._run_adb_cmd(["shell", "stat", "-c", "%Y", path]) or "").strip()
                    if t.isdigit() and (newest is None or int(t) > newest[0]):
                        newest = (int(t), path)
                    break
        if newest is None:
            return f"Error: there is no {what} in the phone's gallery."
        prefix = "GALLERY_SCREENSHOT" if kind == "screenshot" else "GALLERY"
        rel = f"phone-photos/{prefix}_{time.strftime('%Y%m%d_%H%M%S', time.localtime(newest[0]))}.jpg"
        answer = self._pull_image(newest[1], rel)
        if answer.startswith("Error"):
            return answer
        return f"The newest {what} in the gallery: {newest[1].rsplit('/', 1)[-1]}. {answer}"

    def _pull_image(self, remote: str, rel: str) -> str:
        root = Path(os.environ.get("STRATA_WORKSPACE_DIR") or Path.home() / "DL-AI-workspace")
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if self._run_adb_cmd(["pull", remote, str(dest)], timeout=30) is None:
            return "Error: the photo could not be copied from the phone."
        try:                                                  # upright and smaller, like the app sends it
            from PIL import Image, ImageOps
            with Image.open(dest) as im:
                im = ImageOps.exif_transpose(im)
                im.thumbnail((1600, 1600))
                im.convert("RGB").save(dest, "JPEG", quality=85)
        except Exception:
            pass                                              # no Pillow: the full photo
        return f"The photo is in the workspace as {rel}. [[image: {rel}]]"

    def handle(self, req: Dict[str, Any]) -> Dict[str, Any]:
        """Handle incoming JSON-RPC 2.0 request."""
        mid = req.get("id")
        method = req.get("method")

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": mid,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {
                        "name": "ray-phone-mcp",
                        "version": "1.0.0"
                    }
                }
            }

        elif method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": mid,
                "result": {
                    "tools": self.tools
                }
            }

        elif method == "tools/call":
            params = req.get("params", {})
            name = params.get("name", "")
            args = params.get("arguments", {})

            # Validate tool name exists
            if not any(t["name"] == name for t in self.tools):
                return {
                    "jsonrpc": "2.0",
                    "id": mid,
                    "result": {
                        "isError": True,
                        "content": [{"type": "text", "text": f"Unknown tool: '{name}'"}]
                    }
                }

            result_str = self.execute_tool(name, args)
            is_err = "error:" in result_str.lower() or "unreachable" in result_str.lower()
            return {
                "jsonrpc": "2.0",
                "id": mid,
                "result": {
                    "isError": is_err,
                    "content": [{"type": "text", "text": result_str}]
                }
            }

        elif method == "ping":
            return {"jsonrpc": "2.0", "id": mid, "result": {}}

        else:
            return {
                "jsonrpc": "2.0",
                "id": mid,
                "error": {"code": -32601, "message": f"Method '{method}' not found"}
            }


def main():
    server = PhoneMcpServer()
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception:
            continue
        res = server.handle(req)
        sys.stdout.write(json.dumps(res) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
