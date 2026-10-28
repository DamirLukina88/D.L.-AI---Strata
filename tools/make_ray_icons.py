"""make_ray_icons.py - the web app's icons from Ray's own drawing (serve/web/rayface.js): his head, neutral, on the
app's dark surface.

    python3 tools/make_ray_icons.py

Writes serve/web/favicon.svg (crisp squares, for browser tabs), favicon.ico (16, 32, 48 px) and icon-180.png
(apple-touch-icon), icon-192.png, icon-512.png (the web manifest's home-screen icons, drawn as solid dots like Ray on
the page).  Needs node (to run rayface.js's headCell) and Pillow.  Run it again after changing how Ray's head looks.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "serve" / "web"
SURFACE = (18, 22, 27)            # --st-surface of the dark theme

NODE = r"""
const fs = require("fs");
const src = fs.readFileSync(process.argv[1], "utf8");
const noop = () => {};
global.window = {addEventListener: noop, devicePixelRatio: 1};
global.document = {getElementById: () => null};
global.performance = {now: () => 0};
global.requestAnimationFrame = noop;
const R = new Function(src.replace("return {thinking, speakAudio",
  "return {__head: headCell, __pose: newPose, thinking, speakAudio") + "; return RayFace;")();
const s = R.__pose(), rows = [];
for (let j = 0; j < 26; j++) { const r = []; for (let i = 0; i < 44; i++) r.push(R.__head(i + 0.5, j + 0.5, s)); rows.push(r); }
process.stdout.write(JSON.stringify(rows));
"""


def head_grid() -> list[list[str]]:
    out = subprocess.run(["node", "-e", NODE, str(WEB / "rayface.js")], capture_output=True, text=True, check=True)
    grid = json.loads(out.stdout)
    rows = [j for j, r in enumerate(grid) if any(r)]
    cols = [i for r in grid for i, c in enumerate(r) if c]
    return [r[min(cols):max(cols) + 1] for r in grid[min(rows):max(rows) + 1]]


def rgb(c: str) -> tuple[int, int, int]:
    return int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)


def place(grid, size: int, fill: float):
    """cell size and top-left offset that centre the head in a size x size square, filling `fill` of it"""
    h, w = len(grid), len(grid[0])
    cell = size * fill / max(w, h)
    return cell, (size - w * cell) / 2, (size - h * cell) / 2


def png(grid, size: int, dots: bool, radius: float = 0.22) -> Image.Image:
    scale = 4                                      # draw large, then shrink, for smooth edges
    big = size * scale
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, big - 1, big - 1], radius=int(big * radius), fill=SURFACE)
    cell, ox, oy = place(grid, big, 0.78)
    for j, row in enumerate(grid):
        for i, c in enumerate(row):
            if not c:
                continue
            x0, y0 = ox + i * cell, oy + j * cell
            col = rgb(c)
            if dots:                               # Ray's look on the page: a darker backing, a large round dot
                d.rectangle([x0, y0, x0 + cell, y0 + cell], fill=tuple(int(v * 0.8) for v in col))
                r = cell * 0.47
                d.ellipse([x0 + cell / 2 - r, y0 + cell / 2 - r, x0 + cell / 2 + r, y0 + cell / 2 + r], fill=col)
            else:
                d.rectangle([x0, y0, x0 + cell, y0 + cell], fill=col)
    return img.resize((size, size), Image.LANCZOS)


def svg(grid) -> str:
    n = 64
    cell, ox, oy = place(grid, n, 0.82)
    rects = []
    for j, row in enumerate(grid):
        i = 0
        while i < len(row):                        # one rect per run of equal colour
            c = row[i]
            k = i
            while k + 1 < len(row) and row[k + 1] == c:
                k += 1
            if c:
                rects.append(f'<rect x="{ox + i * cell:.2f}" y="{oy + j * cell:.2f}" width="{(k - i + 1) * cell + 0.05:.2f}" '
                             f'height="{cell + 0.05:.2f}" fill="{c}"/>')
            i = k + 1
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {n} {n}" shape-rendering="crispEdges">\n'
            f'<rect width="{n}" height="{n}" rx="14" fill="#12161b"/>\n' + "\n".join(rects) + "\n</svg>\n")


def main() -> int:
    grid = head_grid()
    (WEB / "favicon.svg").write_text(svg(grid))
    png(grid, 48, dots=False).save(WEB / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
    for size in (180, 192, 512):
        png(grid, size, dots=True, radius=0 if size == 180 else 0.22).save(WEB / f"icon-{size}.png", optimize=True)
    print(f"head {len(grid[0])} x {len(grid)} cells -> favicon.svg, favicon.ico, icon-180/192/512.png in {WEB}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
