#!/usr/bin/env python3
"""Log the AMD GPU's temperatures, power, clocks, voltage, fan and load (plus the CPU temperature) every few seconds.

    python tools/gpu_sensor_log.py [--interval 2] [--dir ~/.local/state/dl-ai/gpu-log] [--keep-days 14]

One CSV per day in --dir (2026-11-14.csv), and beside it the board's sensors (2026-11-14-board.csv: every input of
the CPU (k10temp), the motherboard's Super I/O chips (it87xx/nct67xx, gigabyte_wmi), the NVMe drives and ACPI, with
their labels as column names). Every line is flushed and fsync'ed, so after a hard reset the file ends at
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


BOARD_CHIPS = ("k10temp", "zenpower", "it8", "nct6", "gigabyte_wmi", "asus", "nvme", "acpitz")


def board_sensors() -> list[tuple[str, Path, float]]:
    """(column, input file, scale) for every temperature (C), voltage (mV), fan (rpm) and power (W) input of the CPU,
    the motherboard's sensor chips, the NVMe drives and ACPI; the GPU's own sensors are in the main file."""
    out, seen = [], {}
    for h in sorted(Path("/sys/class/hwmon").glob("hwmon*"), key=lambda x: int(x.name[5:] or 0)):
        try:
            name = (h / "name").read_text().strip()
        except OSError:
            continue
        if not name.startswith(BOARD_CHIPS):
            continue
        seen[name] = seen.get(name, 0) + 1
        chip = name if seen[name] == 1 else f"{name}{seen[name]}"
        for f in sorted(h.glob("*_input")):
            kind = f.name.split("_")[0].rstrip("0123456789")
            if kind not in ("temp", "in", "fan", "power"):
                continue
            try:
                label = (h / f.name.replace("_input", "_label")).read_text().strip()
            except OSError:
                label = ""
            col = f"{chip}_{f.name[:-6]}" + (f"_{label}" if label else "")
            col = "".join(c if c.isalnum() or c in "_+-." else "_" for c in col)
            scale = {"temp": 1000.0, "in": 1.0, "fan": 1.0, "power": 1e6}[kind]
            out.append((col, f, scale))
    return out


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

    cpu = hwmon("k10temp")
    gpu = dev = power = None

    def find_gpu():
        """The amdgpu sensors, or None while the card is missing (a boot where it never came up is logged too:
        rows with empty GPU columns and gpu_missing in the last column)."""
        g = hwmon("amdgpu")
        if g is None:
            return None, None, None
        return g, (g / "device").resolve(), (g / "power1_average" if (g / "power1_average").exists()
                                              else g / "power1_input")
    gpu, dev, power = find_gpu()
    if gpu is None:
        print("gpu_sensor_log: no amdgpu sensor found; logging empty GPU rows until it appears", file=sys.stderr)

    stop = False

    def on_term(*_):
        nonlocal stop
        stop = True
    signal.signal(signal.SIGTERM, on_term)
    signal.signal(signal.SIGINT, on_term)

    board = board_sensors()
    day, fh, bh = None, None, None
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
            if bh:
                bh.close()
            bpath = out / f"{day.isoformat()}-board.csv"
            head = ",".join(["time"] + [c for c, _, _ in board])
            bh = open(bpath, "a", encoding="utf-8")
            if not bpath.stat().st_size or bpath.read_text(encoding="utf-8").splitlines()[0] != head:
                bh.write(head + "\n")          # a new file, or the sensor set changed: a new header line
            cutoff = time.time() - a.keep_days * 86400
            for old in out.glob("*.csv"):
                if old.stat().st_mtime < cutoff:
                    old.unlink(missing_ok=True)
        if gpu is None:
            gpu, dev, power = find_gpu()
        row = [now.strftime("%Y-%m-%d %H:%M:%S"),
               *([read(gpu / "temp1_input", 1000), read(gpu / "temp2_input", 1000), read(gpu / "temp3_input", 1000),
                  read(power, 1e6, 1), read(gpu / "power1_cap", 1e6), read(gpu / "in0_input"),
                  read(gpu / "freq1_input", 1e6), read(gpu / "freq2_input", 1e6),
                  read(gpu / "fan1_input"), read(gpu / "pwm1")] if gpu else [""] * 10),
               read(dev / "gpu_busy_percent" if dev else None), read(dev / "mem_busy_percent" if dev else None),
               read(cpu / "temp1_input" if cpu else None, 1000)] + (["gpu_missing"] if gpu is None else [])
        fh.write(",".join(row) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
        bh.write(",".join([row[0]] + [read(p, sc) for _, p, sc in board]) + "\n")
        bh.flush()
        os.fsync(bh.fileno())
        time.sleep(a.interval)
    for h in (fh, bh):
        if h:
            h.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
