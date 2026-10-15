"""tools/dl_schedule.py - scheduled jobs for D.L. AI: run a prompt, or one exact pre-approved action, at a time.

The jobs live in ~/.local/state/dl-ai/schedule.json (mode 600).  The session daemon (dl_sessiond.py) runs them;
`/schedule` there and the on-demand built-in "schedule" (mcp.json {"builtin": "schedule"}) add and remove them.

When:   "2026-10-16 09:00", "09:00" (today, or tomorrow once it has passed), "today 18:30", "tomorrow 07:00",
        "fri 09:00" (the next Friday), "in 2h", "in 1h30m", "in 45m", "in 3d"            -> once
        "daily 08:00", "weekdays 07:30", "mon-fri 07:30", "every mon,wed 18:00", "weekends 10:00",
        "every 2h", "every 30m"                                                             -> repeating
Rules (the user's, 2026-10-15):
- An action job ({"tool", "args"}) is approved when it is scheduled and runs exactly that, without the model.
- A prompt job runs the agent; anything it decides on its own still asks on the Code tab's approval card.
- The model is loaded WARMUP_S before a prompt job; a server that is down is waited for up to RETRY_S, then the
  job fails and a notice goes out.  A job the server dropped half-way is run once more only if it had not acted.
- Missed while the PC or daemon was off: run once at the next start; more than MAX_LATE_S late is skipped.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import threading
import time
from pathlib import Path

STORE = Path.home() / ".local" / "state" / "dl-ai" / "schedule.json"
CONFIG = Path.home() / ".config" / "dl-ai" / "schedule.json"
DEFAULTS = {"notify_email": "", "max_late_h": 12, "retry_min": 30, "warmup_s": 180, "tick_s": 15}
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_lock = threading.RLock()


def settings() -> dict:
    try:
        cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cfg = {}
    return {**DEFAULTS, **{k: v for k, v in cfg.items() if k in DEFAULTS}}


# ---------------------------------------------------------------------- when
class WhenError(ValueError):
    pass


_DUR = re.compile(r"^(?:(\d+(?:\.\d+)?)\s*(d|days?|h|hours?|hrs?|m|mins?|minutes?))+$")
_DUR_PART = re.compile(r"(\d+(?:\.\d+)?)\s*(d|days?|h|hours?|hrs?|m|mins?|minutes?)")
_HM = re.compile(r"^([01]?\d|2[0-3])[:.]([0-5]\d)$")


def _duration(text: str) -> float:
    t = text.replace(" ", "")
    if not _DUR.match(t):
        raise WhenError(f"not a duration: {text!r} (examples: 45m, 2h, 1h30m, 3d)")
    unit = {"d": 86400, "h": 3600, "m": 60}
    return sum(float(n) * unit[u[0]] for n, u in _DUR_PART.findall(t))


def _hm(text: str) -> tuple[int, int]:
    m = _HM.match(text)
    if not m:
        raise WhenError(f"not a time of day: {text!r} (use HH:MM, 24-hour)")
    return int(m.group(1)), int(m.group(2))


def _days(text: str) -> list[int]:
    t = text.lower()
    named = {"daily": range(7), "everyday": range(7), "day": range(7), "weekdays": range(5), "weekends": (5, 6),
             "weekend": (5, 6)}
    if t in named:
        return sorted(named[t])
    out: set[int] = set()
    for part in t.split(","):
        a, _, b = part.partition("-")
        ia, ib = _day(a), _day(b) if b else None
        if ib is None:
            out.add(ia)
        else:
            i = ia
            while True:
                out.add(i)
                if i == ib:
                    break
                i = (i + 1) % 7
    return sorted(out)


HR_DAYS = ["pon", "uto", "sri", "čet", "pet", "sub", "ned"]


def _day(word: str) -> int:
    w = word.strip().lower()[:3].replace("cet", "čet")
    if w in DAYS:
        return DAYS.index(w)
    if w in HR_DAYS:
        return HR_DAYS.index(w)
    raise WhenError(f"not a weekday: {word!r} (mon, tue, wed, thu, fri, sat, sun)")


def _is_days(word: str) -> bool:
    try:
        _days(word)
        return True
    except WhenError:
        return False


_HR_DATE = re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})?\.?$")
_HR_DAY_MONTH = re.compile(r"^(\d{1,2})\.(\d{1,2})()$")         # "16.10" followed by a time: a date, not 16:10


def parse_when(text: str, now: float | None = None, anchor: float | None = None) -> tuple[dict, str]:
    """'tomorrow 07:00 check my mail' -> (spec, 'check my mail').  The spec is stored; next_run() reads it.

    `anchor`: when the user asked (the start of the turn).  A time still ahead then but passed by now - the work took
    longer - runs at once and keeps the asked-for time as "planned", so the delay is reported; it never moves to
    tomorrow.  A time already past when the user asked: a bare HH:MM means tomorrow, a date is an error."""
    now = time.time() if now is None else now
    anchor = now if anchor is None or anchor > now else anchor
    words = (text or "").strip().split()
    if not words:
        raise WhenError("say when: e.g. 'tomorrow 09:00', 'in 2h', 'daily 08:00'")
    w0 = words[0].lower()
    base = dt.datetime.fromtimestamp(anchor)

    def once(at, used: int):
        t = at.timestamp() if isinstance(at, dt.datetime) else float(at)
        if t <= anchor:
            raise WhenError(f"{fmt(t)} had already passed when you asked")
        rest = " ".join(words[used:])
        if t <= now:
            return {"kind": "once", "at": now, "planned": t}, rest
        return {"kind": "once", "at": t}, rest

    def day_at(d: dt.datetime, hm: str) -> dt.datetime:
        h, m = _hm(hm)
        return d.replace(hour=h, minute=m, second=0, microsecond=0)

    if w0 in ("in", "za") and len(words) > 1:
        for n in (3, 2, 1):                          # "in 1h 30m", "in 2 h", "in 2h"
            try:
                return once(anchor + _duration("".join(words[1:1 + n])), 1 + n)
            except WhenError as e:
                if "passed" in str(e):
                    raise
                continue
        raise WhenError(f"not a duration after 'in': {' '.join(words[1:3])!r}")
    if w0 == "every" and len(words) > 1:
        try:
            secs = _duration(words[1])
            if secs < 60:
                raise WhenError("the shortest repeat is every 1m")
            return {"kind": "every", "seconds": secs, "start": now}, " ".join(words[2:])
        except WhenError as e:
            if "shortest" in str(e):
                raise
        if len(words) > 2 and _is_days(words[1]):
            h, m = _hm(words[2])
            return {"kind": "days", "time": f"{h:02d}:{m:02d}", "days": _days(words[1])}, " ".join(words[3:])
        if len(words) > 2 and words[1].lower() == "day":
            h, m = _hm(words[2])
            return {"kind": "days", "time": f"{h:02d}:{m:02d}", "days": list(range(7))}, " ".join(words[3:])
        raise WhenError("after 'every' give a duration (every 2h) or days and a time (every mon,wed 18:00)")
    if re.match(r"^\d{4}-\d{2}-\d{2}([t ]\d{1,2}[:.]\d{2})?$", w0):
        if "t" in w0:
            d, _, hm = w0.partition("t")
            used = 1
        else:
            d, hm, used = w0, (words[1] if len(words) > 1 else ""), 2
        try:
            day = dt.datetime.strptime(d, "%Y-%m-%d")
        except ValueError:
            raise WhenError(f"not a date: {d!r} (YYYY-MM-DD or DD.MM.YYYY.)") from None
        return once(day_at(day, hm), used)
    m = _HR_DATE.match(w0) or (_HR_DAY_MONTH.match(w0) if len(words) > 1 and _HM.match(words[1]) else None)
    if m and len(words) > 1:                         # 16.10.2026. 21:30 / 16.10. 21:30 / 16.10 21:30
        try:
            day = dt.datetime(int(m.group(3) or base.year), int(m.group(2)), int(m.group(1)))
        except ValueError:
            raise WhenError(f"not a date: {w0!r} (DD.MM.YYYY.)") from None
        at = day_at(day, words[1])
        if not m.group(3) and at.timestamp() <= anchor:
            at = at.replace(year=at.year + 1)
        return once(at, 2)
    if w0 in ("today", "danas", "tomorrow", "sutra") and len(words) > 1:
        return once(day_at(base, words[1]) + dt.timedelta(days=w0 in ("tomorrow", "sutra")), 2)
    if _HM.match(w0):
        at = day_at(base, w0)
        if at.timestamp() <= anchor:                 # already past when asked: tomorrow
            at += dt.timedelta(days=1)
        return once(at, 1)
    if len(words) > 1 and _HM.match(words[1]) and _is_days(w0):
        h, mi = _hm(words[1])
        days = _days(w0)
        if len(days) == 1 and w0 not in ("daily", "everyday"):  # "fri 09:00": the next Friday, once
            at = day_at(base, words[1])
            at += dt.timedelta(days=(days[0] - at.weekday()) % 7)
            if at.timestamp() <= anchor:
                at += dt.timedelta(days=7)
            return once(at, 2)
        return {"kind": "days", "time": f"{h:02d}:{mi:02d}", "days": days}, " ".join(words[2:])
    raise WhenError(f"can't read the time in {' '.join(words[:3])!r}: use e.g. '16.10.2026. 09:00', 'tomorrow 07:00', "
                    "'fri 09:00', 'in 2h', 'daily 08:00', 'mon-fri 07:30', 'every 2h'")


def next_run(spec: dict, after: float) -> float | None:
    """The first run strictly after `after`; None when a one-off has nothing left."""
    kind = spec.get("kind")
    if kind == "once":
        return spec["at"] if spec["at"] > after else None
    if kind == "every":
        step, start = float(spec["seconds"]), float(spec["start"])
        n = int((after - start) // step) + 1
        return start + max(n, 1) * step
    if kind == "days":
        h, m = map(int, spec["time"].split(":"))
        d = dt.datetime.fromtimestamp(after).replace(hour=h, minute=m, second=0, microsecond=0)
        for i in range(8):
            c = d + dt.timedelta(days=i)
            if c.weekday() in spec["days"] and c.timestamp() > after:
                return c.timestamp()
    return None


def last_due(spec: dict, scheduled: float, now: float) -> float:
    """The latest run time at or before `now` (a repeating job missed several times counts from its last one)."""
    kind = spec.get("kind")
    if kind == "every":
        step, start = float(spec["seconds"]), float(spec["start"])
        return max(scheduled, start + ((now - start) // step) * step)
    if kind == "days":
        h, m = map(int, spec["time"].split(":"))
        d = dt.datetime.fromtimestamp(now).replace(hour=h, minute=m, second=0, microsecond=0)
        for i in range(8):
            c = d - dt.timedelta(days=i)
            if c.weekday() in spec["days"] and scheduled <= c.timestamp() <= now:
                return c.timestamp()
    return scheduled


def describe(spec: dict) -> str:
    kind = spec.get("kind")
    if kind == "once":
        return "once at " + fmt(spec.get("planned") or spec["at"])
    if kind == "every":
        s = spec["seconds"]
        return "every " + (f"{s / 3600:g}h" if s >= 3600 else f"{s / 60:g}m")
    days = spec["days"]
    names = ("daily" if len(days) == 7 else "weekdays" if days == [0, 1, 2, 3, 4] else
             "weekends" if days == [5, 6] else ",".join(HR_DAYS[d] for d in days))
    return f"{names} {spec['time']}"


def fmt(ts: float | None) -> str:
    """Croatian date and time: 'pet 16.10.2026. 21:30'."""
    if not ts:
        return "-"
    d = dt.datetime.fromtimestamp(ts)
    return f"{HR_DAYS[d.weekday()]} {d:%d.%m.%Y.} {d:%H:%M}"


def hm(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts).strftime("%H:%M")


def until(ts: float, now: float | None = None) -> str:
    s = max(0, ts - (time.time() if now is None else now))
    if s < 3600:
        return f"in {int(s // 60)} min"
    if s < 2 * 86400:
        return f"in {s / 3600:.1f} h"
    return f"in {s / 86400:.1f} days"


# ---------------------------------------------------------------------- store
def load() -> dict:
    try:
        data = json.loads(STORE.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("jobs"), list):
            return data
    except (OSError, ValueError):
        pass
    return {"next_id": 1, "jobs": []}


def save(data: dict) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(STORE)


def add(when: str, prompt: str = "", action: dict | None = None, email_result: bool = False,
        workspace: str = "", now: float | None = None, anchor: float | None = None, yolo: bool = False) -> dict:
    """Add a job; `when` may carry the prompt after the time ('daily 08:00 summarise my mail').  `anchor`: when the
    user asked; `yolo`: scheduled while YOLO was on, so the job runs without asking too."""
    now = time.time() if now is None else now
    spec, rest = parse_when(when, now, anchor)
    prompt = (prompt or rest or "").strip()
    if not prompt and not action:
        raise WhenError("nothing to do: give a prompt (or an action)")
    first = next_run(spec, now - 1) if spec["kind"] == "once" else next_run(spec, now)
    with _lock:
        data = load()
        job = {"id": data["next_id"], "when": when.strip(), "spec": spec, "prompt": prompt, "action": action,
               "email_result": bool(email_result), "workspace": workspace, "enabled": True, "next": first,
               "created": now, "runs": 0, "last": None, "yolo": bool(yolo)}
        data["next_id"] += 1
        data["jobs"].append(job)
        save(data)
    return job


def remove(job_id: int) -> dict | None:
    with _lock:
        data = load()
        job = next((j for j in data["jobs"] if j["id"] == int(job_id)), None)
        if job:
            data["jobs"].remove(job)
            save(data)
        return job


def set_enabled(job_id: int, on: bool, now: float | None = None) -> dict | None:
    now = time.time() if now is None else now
    with _lock:
        data = load()
        job = next((j for j in data["jobs"] if j["id"] == int(job_id)), None)
        if job:
            job["enabled"] = on
            if on and (not job.get("next") or job["next"] < now):
                job["next"] = next_run(job["spec"], now)
                job["enabled"] = job["next"] is not None
            save(data)
        return job


def summary(job: dict) -> str:
    what = (f"action {job['action'].get('tool')}" if job.get("action") else job.get("prompt", ""))[:120]
    state = (f"next {fmt(job['next'])} ({until(job['next'])})" if job.get("enabled") and job.get("next")
             else "off" if job.get("next") else "done")
    last = job.get("last") or {}
    tail = f"; last {last['status']} {fmt(last.get('at'))}" if last else ""
    mail = "; result by email" if job.get("email_result") else ""
    late = ""
    if job["spec"].get("planned"):
        late = (f"; planned {hm(job['spec']['planned'])}, already passed: runs at once, "
                f"{(job['spec']['at'] - job['spec']['planned']) / 60:.0f} min late")
    return f"#{job['id']} {describe(job['spec'])}: {what}  [{state}{tail}{mail}{late}]"


def list_text() -> str:
    jobs = load()["jobs"]
    if not jobs:
        return "No scheduled jobs."
    return "\n".join(summary(j) for j in jobs)


# ---------------------------------------------------------------------- the built-in tool
TOOLS = [
    {"name": "add", "description": (
        "Schedule a job. `when`: '2026-10-16 09:00', 'tomorrow 07:00', 'fri 09:00', 'in 2h', 'daily 08:00', "
        "'mon-fri 07:30', 'every mon,wed 18:00', 'every 2h' (local time, 24-hour). `prompt`: what the assistant "
        "does then. To get the result by email set email_result, don't ask the job to send mail. To send one exact "
        "email or do one exact action at that time, give `action` {tool, args} with a tool you have (e.g. "
        "proton__send_mail; turn its server on first): the user approves it now, and it runs exactly so, without the "
        "model. Always give the time the user asked for, even if it has passed while you worked: the job then runs at "
        "once and the delay is reported (and noted in an email it sends). Never move it to tomorrow or ask."),
     "inputSchema": {"type": "object", "properties": {
         "when": {"type": "string"}, "prompt": {"type": "string"},
         "email_result": {"type": "boolean", "description": "Email the result to the user"},
         "action": {"type": "object", "properties": {"tool": {"type": "string"}, "args": {"type": "object"}},
                    "required": ["tool", "args"]}},
         "required": ["when"]}},
    {"name": "list", "description": "List the scheduled jobs.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "remove", "description": "Delete a scheduled job by its number.",
     "inputSchema": {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]}},
]


def _context() -> dict:
    try:
        import dl_mcp
        return dl_mcp.call_context()
    except ImportError:
        return {}


def check_action(action: dict, registry) -> str | None:
    """A scheduled action must name a tool that is on now, with only its own parameters: else it would fail (or
    drop a parameter silently) at the time it runs, with nobody watching."""
    tool, args = str(action.get("tool")), action.get("args") or {}
    if registry is None or "__" not in tool:
        return None
    if not registry.owns(tool):
        server = tool.split("__", 1)[0]
        return (f"{tool} is not available now: turn on {server!r} first (mcp enable) so its parameters are known, "
                "then schedule again")
    bad = registry.unknown_args(tool, args)
    return bad.removeprefix("error: ") if bad else None


def call(tool: str, args: dict) -> str:
    a = dict(args or {})
    try:
        if tool == "add":
            action = a.get("action") or None
            if action is not None and (not isinstance(action, dict) or not action.get("tool")
                                       or not isinstance(action.get("args"), dict)):
                return "Error: action must be {\"tool\": \"<tool name>\", \"args\": {...}}"
            if action and str(action["tool"]).startswith("schedule__"):
                return "Error: a job cannot schedule jobs"
            ctx = _context()
            if action:
                bad = check_action(action, ctx.get("registry"))
                if bad:
                    return f"Error: {bad}"
            job = add(str(a.get("when") or ""), str(a.get("prompt") or ""), action,
                      bool(a.get("email_result")), str(a.get("workspace") or ctx.get("workspace") or ""),
                      anchor=ctx.get("request_time"), yolo=bool(ctx.get("yolo")))
            return f"Scheduled {summary(job)}"
        if tool == "list":
            return list_text()
        if tool == "remove":
            job = remove(int(a.get("id") or 0))
            return f"Removed #{job['id']}." if job else f"Error: no job #{a.get('id')}"
    except WhenError as e:
        return f"Error: {e}"
    except (TypeError, ValueError) as e:
        return f"Error: {e}"
    return f"Error: unknown tool {tool!r}"


# ---------------------------------------------------------------------- the runner (in the daemon)
class Scheduler:
    """Runs due jobs one at a time in its own thread.  The daemon gives it what it needs:

    run_prompt(job) -> {"ok": bool, "text": str, "acted": bool, "server_error": bool}
    run_action(job) -> {"ok": bool, "text": str}
    health() -> bool            the Strata server answers /health
    warm() -> None              load the model now
    post(title, text, level)    show it in the Code tab
    notify(subject, body)       email the user (may do nothing)
    """

    def __init__(self, run_prompt, run_action, health, warm, post, notify, clock=time.time, sleep=time.sleep):
        self.run_prompt, self.run_action = run_prompt, run_action
        self.health, self.warm, self.post, self.notify = health, warm, post, notify
        self.clock, self.sleep = clock, sleep
        self.stop = threading.Event()
        self.warmed: dict[int, float] = {}
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        self.thread = threading.Thread(target=self._loop, name="dl-schedule", daemon=True)
        self.thread.start()

    def _loop(self) -> None:
        while not self.stop.is_set():
            try:
                self.tick()
            except Exception as e:  # noqa: BLE001 - the scheduler must keep running
                self.post("Scheduler error", f"{type(e).__name__}: {e}", "warn")
            self.stop.wait(float(settings()["tick_s"]))

    def tick(self) -> list[int]:
        """Warm up for jobs coming soon, then run what is due.  Returns the ids that ran (for the tests)."""
        cfg, now = settings(), self.clock()
        with _lock:
            data = load()
            due, changed = [], False
            for job in data["jobs"]:
                if not job.get("enabled") or not job.get("next"):
                    continue
                if (not job.get("action") and 0 < job["next"] - now <= float(cfg["warmup_s"])
                        and self.warmed.get(job["id"]) != job["next"]):
                    self.warmed[job["id"]] = job["next"]
                    threading.Thread(target=self._warm, daemon=True).start()
                if job["next"] > now:
                    continue
                scheduled = last_due(job["spec"], job["next"], now)
                late = now - scheduled
                job["next"] = next_run(job["spec"], now)        # repeating: one catch-up run, not every missed one
                if job["next"] is None:
                    job["enabled"] = False
                changed = True
                if late > float(cfg["max_late_h"]) * 3600:
                    job["last"] = {"at": now, "status": "skipped", "text": f"{late / 3600:.1f} h late"}
                    self.post(f"Skipped job #{job['id']}", f"{summary(job)}\nIt was due {fmt(scheduled)} and is "
                              f"{late / 3600:.1f} h late (the limit is {cfg['max_late_h']} h).", "warn")
                    self.notify(f"D.L. AI: job #{job['id']} skipped",
                                f"The scheduled job #{job['id']} was due {fmt(scheduled)} but the PC or the daemon "
                                f"was off; it is {late / 3600:.1f} h late, so it was skipped.\n\n{job.get('prompt')}")
                    continue
                due.append((dict(job), late))
            if changed:
                save(data)
        ran = []
        for job, late in due:
            self._run(job, late)
            ran.append(job["id"])
        return ran

    def _warm(self) -> None:
        try:
            if self.health():
                self.warm()
        except Exception:  # noqa: BLE001 - warming up is a convenience
            pass

    def _wait_health(self) -> bool:
        deadline = self.clock() + float(settings()["retry_min"]) * 60
        while True:
            try:
                if self.health():
                    return True
            except Exception:  # noqa: BLE001
                pass
            if self.clock() >= deadline or self.stop.is_set():
                return False
            self.sleep(60)

    def _run(self, job: dict, late: float) -> None:
        planned = job["spec"].get("planned")
        if planned:                                    # passed while the user's request was being worked on
            late = max(late, self.clock() - planned)
        job["late_s"], job["planned_at"] = late, (planned or self.clock() - late)
        note = f" (late by {late / 60:.0f} min)" if late > 120 else ""
        title = f"Scheduled job #{job['id']}{note}"
        if job.get("action"):
            res = self.run_action(job)
            status = "ok" if res["ok"] else "failed"
        elif not self._wait_health():
            res = {"ok": False, "text": f"the Strata server did not answer for {settings()['retry_min']} min"}
            status = "failed"
        else:
            res = self.run_prompt(job)
            status = "ok" if res["ok"] else "failed"
            if not res["ok"] and res.get("server_error"):
                if res.get("acted"):
                    status = "interrupted"            # it may have done part of the work: never twice
                elif self._wait_health():
                    res = self.run_prompt(job)        # it had only read: once more
                    status = "ok" if res["ok"] else "failed"
        self._record(job["id"], status, res["text"])
        text = res["text"] or "(no answer)"
        self.post(f"{title}: {status}", f"{job.get('prompt') or job['action'].get('tool')}\n\n{text}",
                  "info" if status == "ok" else "warn")
        if status != "ok":
            what = {"failed": "failed", "interrupted": "was interrupted half-way and was not run again"}[status]
            self.notify(f"D.L. AI: job #{job['id']} {status}",
                        f"The scheduled job #{job['id']} ({describe(job['spec'])}) {what}.\n\n"
                        f"Job: {job.get('prompt') or job['action'].get('tool')}\n\n{text[:3000]}")
        elif job.get("email_result") and not job.get("action"):
            self.notify(f"D.L. AI: {(job.get('prompt') or '')[:60]}", text[:20000])

    def _record(self, job_id: int, status: str, text: str) -> None:
        with _lock:
            data = load()
            for j in data["jobs"]:
                if j["id"] == job_id:
                    j["runs"] = int(j.get("runs") or 0) + 1
                    j["last"] = {"at": self.clock(), "status": status, "text": (text or "")[:500]}
            save(data)
