"""Write a short synthetic crater video for packaged-app smoke tests."""

import sys

import cv2
import numpy as np

path = sys.argv[1] if len(sys.argv) > 1 else "sample.mp4"
w, h = 640, 360
writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), 24.0, (w, h))
xs = np.arange(w)
surface = 180 + np.where((xs > 220) & (xs < 420), 40 * np.sin(np.pi * (xs - 220) / 200) ** 2, 0)
for i in range(48):
    frame = np.full((h, w, 3), 220, np.uint8)
    poly = np.vstack([np.column_stack([xs, surface]), [[w - 1, h - 1], [0, h - 1]]]).astype(np.int32)
    cv2.fillPoly(frame, [poly], (60, 50, 70))
    writer.write(frame)
writer.release()
print(path)
