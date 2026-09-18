"""Write a short synthetic crater video for packaged-app smoke tests.

Prints the path actually written: if the requested container cannot be
encoded on this machine it falls back to MJPG in .avi, and it fails loudly
if nothing readable could be produced.
"""

import sys
from pathlib import Path

import cv2
import numpy as np


def frames(w=640, h=360, count=48):
    xs = np.arange(w)
    surface = 180 + np.where((xs > 220) & (xs < 420), 40 * np.sin(np.pi * (xs - 220) / 200) ** 2, 0)
    poly = np.vstack([np.column_stack([xs, surface]), [[w - 1, h - 1], [0, h - 1]]]).astype(np.int32)
    for _ in range(count):
        frame = np.full((h, w, 3), 220, np.uint8)
        cv2.fillPoly(frame, [poly], (60, 50, 70))
        yield frame


def write(path: Path, fourcc: str) -> bool:
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*fourcc), 24.0, (640, 360))
    if not writer.isOpened():
        return False
    for frame in frames():
        writer.write(frame)
    writer.release()
    cap = cv2.VideoCapture(str(path))
    ok, _ = cap.read()
    cap.release()
    return ok


def main() -> int:
    requested = Path(sys.argv[1] if len(sys.argv) > 1 else "sample.mp4")
    for path, fourcc in ((requested, "mp4v"), (requested, "avc1"), (requested.with_suffix(".avi"), "MJPG")):
        if write(path, fourcc):
            print(path)
            return 0
    print("could not write a readable sample video", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
