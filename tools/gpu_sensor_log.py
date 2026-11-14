#!/usr/bin/env python3
"""Log the AMD GPU's temperatures, power, clocks, voltage, fan and load (plus the CPU temperature) every few seconds.

    python tools/gpu_sensor_log.py [--interval 2] [--dir ~/.local/state/dl-ai/gpu-log] [--keep-days 14]

One CSV per day in --dir (2026-11-14.csv). Every line is flushed and fsync'ed, so after a hard reset the file ends at
the last reading before the crash: `tail` the newest file after the next restart. Files older than --keep-days are
deleted. Standard library only; reads /sys and changes nothing.
"""
from __future__ import annotations

import argparse
import datetime
import os
import signal
import sys
import time
from pathlib import Path

FIELDS = ["time", "edge_c", "junction_c", "mem_c", "power_w", "power_cap_w", "vddgfx_mv", "sclk_mhz", "mclk_mhz",
          "fan_rpm", "pwm", "gpu_busy_pct", "mem_busy_pct", "cpu_tctl_c"]


def hwmon(name: str) -> Path | None:
    for h in sorted(Path("/sys/class/hwmon").glob("hwmon*")):
        try:
            if (h / "name").read_text().strip() == name:
                return h
        except OSError:
            pass
    return None


def read(p: Path | None, scale: float = 1.0, digits: int = 0) -> str:
    if p is None:
        return ""
    try:
        v = int(p.read_text().strip()) / scale
    except (OSError, ValueError):
        return ""
    return f"{v:.{digits}f}" if digits else str(round(v))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--interval", type=float, default=2.0)
    ap.add_argument("--dir", default="~/.local/state/dl-ai/gpu-log")
    ap.add_argument("--keep-days", type=int, default=14)
    a = ap.parse_args()
    out = Path(a.dir).expanduser()
    out.mkdir(parents=True, exist_ok=True)

    gpu = hwmon("amdgpu")
    if gpu is None:
        print("gpu_sensor_log: no amdgpu sensor found", file=sys.stderr)
        return 1
    dev = (gpu / "device").resolve()
    cpu = hwmon("k10temp")
    power = gpu / "power1_average" if (gpu / "power1_average").exists() else gpu / "power1_input"

    stop = False

    def on_term(*_):
        nonlocal stop
        stop = True
    signal.signal(signal.SIGTERM, on_term)
    signal.signal(signal.SIGINT, on_term)

    day, fh = None, None
    while not stop:
        now = datetime.datetime.now()
        if now.date() != day:
            if fh:
                fh.close()
            day = now.date()
            path = out / f"{day.isoformat()}.csv"
            new = not path.exists()
            fh = open(path, "a", encoding="utf-8")
            if new:
                fh.write(",".join(FIELDS) + "\n")
            cutoff = time.time() - a.keep_days * 86400
            for old in out.glob("*.csv"):
                if old.stat().st_mtime < cutoff:
                    old.unlink(missing_ok=True)
        row = [now.strftime("%Y-%m-%d %H:%M:%S"),
               read(gpu / "temp1_input", 1000), read(gpu / "temp2_input", 1000), read(gpu / "temp3_input", 1000),
               read(power, 1e6, 1), read(gpu / "power1_cap", 1e6), read(gpu / "in0_input"),
               read(gpu / "freq1_input", 1e6), read(gpu / "freq2_input", 1e6),
               read(gpu / "fan1_input"), read(gpu / "pwm1"),
               read(dev / "gpu_busy_percent"), read(dev / "mem_busy_percent"),
               read(cpu / "temp1_input" if cpu else None, 1000)]
        fh.write(",".join(row) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
        time.sleep(a.interval)
    if fh:
        fh.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
