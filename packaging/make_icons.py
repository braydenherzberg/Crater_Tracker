"""Regenerate the app icon (PNG, ICO, ICNS) from code: python packaging/make_icons.py"""

from __future__ import annotations

import shutil
import struct
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT.parent / "crater_app" / "desktop" / "assets"


def draw(size: int = 1024) -> np.ndarray:
    s = 4  # supersample
    n = size * s
    img = np.zeros((n, n, 4), dtype=np.uint8)
    pad, radius = int(n * 0.08), int(n * 0.2)
    bg = (20, 20, 20, 255)
    cv2.rectangle(img, (pad + radius, pad), (n - pad - radius, n - pad), bg, -1)
    cv2.rectangle(img, (pad, pad + radius), (n - pad, n - pad - radius), bg, -1)
    for cx, cy in ((pad + radius, pad + radius), (n - pad - radius, pad + radius),
                   (pad + radius, n - pad - radius), (n - pad - radius, n - pad - radius)):
        cv2.circle(img, (cx, cy), radius, bg, -1)
    xs = np.linspace(pad * 1.9, n - pad * 1.9, 400)
    rel = (xs - xs[0]) / (xs[-1] - xs[0])
    base = n * 0.46
    y = base - n * 0.035 * np.exp(-((rel - 0.24) / 0.05) ** 2) - n * 0.035 * np.exp(-((rel - 0.76) / 0.05) ** 2)
    inside = (rel > 0.24) & (rel < 0.76)
    y[inside] += n * 0.2 * np.sin(np.pi * (rel[inside] - 0.24) / 0.52) ** 2
    # material below the line
    poly = np.vstack([np.column_stack([xs, y]), [[xs[-1], n - pad * 1.9], [xs[0], n - pad * 1.9]]]).astype(np.int32)
    cv2.fillPoly(img, [poly], (40, 40, 40, 255))
    cv2.polylines(img, [np.column_stack([xs, y]).astype(np.int32)], False, (26, 169, 229, 255), int(n * 0.028), cv2.LINE_AA)
    for fx in (0.24, 0.76):
        x = int(xs[0] + fx * (xs[-1] - xs[0]))
        cv2.line(img, (x, int(base - n * 0.1)), (x, int(base + n * 0.02)), (224, 228, 228, 255), int(n * 0.012), cv2.LINE_AA)
    return cv2.resize(img, (size, size), interpolation=cv2.INTER_AREA)


def write_ico(path: Path, image: np.ndarray, sizes=(16, 24, 32, 48, 64, 128, 256)) -> None:
    blobs = []
    for size in sizes:
        ok, png = cv2.imencode(".png", cv2.resize(image, (size, size), interpolation=cv2.INTER_AREA))
        blobs.append((size, png.tobytes()))
    header = struct.pack("<HHH", 0, 1, len(blobs))
    offset = 6 + 16 * len(blobs)
    entries, data = b"", b""
    for size, blob in blobs:
        entries += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(blob), offset + len(data))
        data += blob
    path.write_bytes(header + entries + data)


def main() -> int:
    ASSETS.mkdir(parents=True, exist_ok=True)
    image = draw()
    cv2.imwrite(str(ASSETS / "icon.png"), cv2.resize(image, (512, 512), interpolation=cv2.INTER_AREA))
    write_ico(ROOT / "icon.ico", image)
    if sys.platform == "darwin" and shutil.which("iconutil"):
        iconset = ROOT / "icon.iconset"
        iconset.mkdir(exist_ok=True)
        for size in (16, 32, 128, 256, 512):
            for scale in (1, 2):
                px = size * scale
                name = f"icon_{size}x{size}{'@2x' if scale == 2 else ''}.png"
                cv2.imwrite(str(iconset / name), cv2.resize(image, (px, px), interpolation=cv2.INTER_AREA))
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(ROOT / "icon.icns")], check=True)
        shutil.rmtree(iconset)
    print("icons written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
