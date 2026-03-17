from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Dict, List

import cv2
import numpy as np


def export_metrics_csv(rows: List[Dict], target_csv: str) -> None:
    target = Path(target_csv)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        with target.open("w", newline="", encoding="utf-8") as handle:
            handle.write("")
        return
    fieldnames = list(rows[0].keys())
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def export_snapshot(image: np.ndarray, target_path: str) -> None:
    target = Path(target_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(target), image)


def export_profile_csv(rows: List[Dict], target_csv: str) -> None:
    """Write calibrated profile data (frame, timestamp_ms, x_mm, y_mm) to CSV."""
    target = Path(target_csv)
    target.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["frame", "timestamp_ms", "x_mm", "y_mm"]
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def export_session_json(payload: Dict, target_json: str) -> None:
    target = Path(target_json)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


def export_starred_session(payload: Dict, target_json: str) -> None:
    """Write a starred-frames session (video path + per-frame settings/profiles) to JSON."""
    target = Path(target_json)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)

