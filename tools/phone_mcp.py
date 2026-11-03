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
11. phone_get_last_photo - the newest photo again
12. phone_get_screen - Accessibility screen inspection
"""
import json
import os
import re
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
        "description": "Turn the phone flashlight / torch on or off.",
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
        "description": "Get current phone battery percentage, charging state, voltage, temperature, and battery health.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "phone_set_volume",
        "description": "Set phone volume level for media, ring, alarm, or notification.",
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
        "description": "Set an alarm on the phone for a specific hour and minute with an optional label.",
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
        "description": "Open or launch an application on the phone by app name or package name (e.g. 'spotify', 'youtube', 'settings', 'camera').",
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
        "description": "Retrieve recent notifications posted to the phone status bar.",
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
        "description": "Extract the most recent 2FA / OTP verification code from SMS or notifications (supports Croatian banking and English formats).",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "phone_get_now_playing",
        "description": "Get information about currently playing media (Spotify, YouTube, etc.) including title, artist, and playback state.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "phone_control_media",
        "description": "Control phone media playback (play, pause, next, previous, stop).",
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
        "description": "Take a photo with the phone's back camera and see it: the photo comes back to you as an image. The phone plays the shutter sound. Works only while Ray is on the phone's screen (the app or the voice drawer) and the phone is unlocked; point the phone first.",
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
        "description": "Show the newest photo again (it is in the workspace under phone-photos/); if none was taken in the last 2 minutes, it takes one now like phone_camera_snap. Only works while the phone is unlocked and Ray is on its screen.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "phone_get_screen",
        "description": "Inspect visible text and UI elements currently displayed on the phone screen via Accessibility.",
        "inputSchema": {
            "type": "object",
            "properties": {}
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
        if not self.adb_enabled:
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
        payload = json.dumps({"tool": tool_name, "args": args}).encode("utf-8")
        try:
            req = urllib.request.Request(
                f"{self.base_url}/api/phone/tool/call",
                data=payload,
                headers=self._headers(True)
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode())
                if "result" in data:
                    return str(data["result"])
        except Exception:
            pass
        return None

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
            "--es", "args", json.dumps(args)
        ]
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
        root = Path(os.environ.get("STRATA_WORKSPACE_DIR") or Path.home() / "DL-AI-workspace")
        rel = f"phone-photos/{newest.rsplit('_', 1)[0]}.jpg"
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if self._run_adb_cmd(["pull", f"{self.PHOTO_DIR}/{newest}", str(dest)], timeout=30) is None:
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
