"""Measure a crater through time from operator keyframes.

Every sampled frame between the first and last keyframe is analysed with the
guide that applies to it (the keyframe itself, or one interpolated between its
neighbours) and the result is written as one calibrated row per frame. The
``source`` and ``frames_to_key`` columns keep interpolated rows distinguishable
from operator-verified keyframes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

from .analysis import AnalysisEngine, AnalysisResult
from .guided_profile import GuideSample, Point, guide_for_frame
from .settings import AnalysisSettings
from .video_reader import iter_frames

SERIES_FIELDS = [
    "frame",
    "time_s",
    "source",
    "frames_to_key",
    "width_mm",
    "depth_mm",
    "area_mm2",
    "baseline_tilt_deg",
    "left_rim_x_mm",
    "right_rim_x_mm",
    "deepest_x_mm",
    "edge_support",
    "confidence",
    "notes",
]


@dataclass
class FrameMeasurement:
    result: AnalysisResult
    guide: GuideSample


def measure_frame(
    engine: AnalysisEngine,
    frame: np.ndarray,
    keyframes: Dict[int, Sequence[Point]],
    frame_index: int,
    *,
    snap: bool = True,
    settings: Optional[AnalysisSettings] = None,
) -> Optional[FrameMeasurement]:
    guide = guide_for_frame(keyframes, frame_index)
    if guide is None:
        return None
    result = engine.analyze_guided_frame(
        frame,
        settings or AnalysisSettings(),
        guide.points,
        is_keyframe=guide.source == "keyframe",
        snap_to_edge=snap,
        annotation_confidence=guide.annotation_confidence,
    )
    return FrameMeasurement(result, guide)


def measurement_row(
    measurement: FrameMeasurement, frame_index: int, fps: float, mm_per_px: float
) -> Dict:
    result, guide = measurement.result, measurement.guide
    geometry, metrics = result.geometry, result.metrics
    row = {
        "frame": frame_index,
        "time_s": round(frame_index / fps, 6) if fps > 0 else "",
        "source": guide.source,
        "frames_to_key": guide.frames_to_key,
    }
    if geometry is None:
        row.update({field: "" for field in SERIES_FIELDS[4:]})
        row["notes"] = "no crater found on this line"
        return row
    row.update(
        {
            "width_mm": round(metrics.max_crater_width_px * mm_per_px, 4),
            "depth_mm": round(metrics.max_crater_depth_px * mm_per_px, 4),
            "area_mm2": round(metrics.crater_area_px * mm_per_px**2, 4),
            "baseline_tilt_deg": round(metrics.baseline_tilt_degrees, 3),
            "left_rim_x_mm": round(geometry.left_rim[0] * mm_per_px, 4),
            "right_rim_x_mm": round(geometry.right_rim[0] * mm_per_px, 4),
            "deepest_x_mm": round(geometry.center[0] * mm_per_px, 4),
            "edge_support": round(geometry.profile_confidence, 3),
            "confidence": round(geometry.geometry_confidence, 3),
            "notes": " ".join(geometry.notes),
        }
    )
    return row


def profile_rows(
    measurement: FrameMeasurement, frame_index: int, mm_per_px: float
) -> List[Dict]:
    geometry = measurement.result.geometry
    if geometry is None:
        return []
    return [
        {
            "frame": frame_index,
            "x_mm": round(x * mm_per_px, 4),
            "y_mm": round(y * mm_per_px, 4),
            "baseline_y_mm": round(by * mm_per_px, 4),
        }
        for (x, y), (_, by) in zip(geometry.crater_points, geometry.baseline_points)
    ]


def keyframe_span(keyframes: Dict[int, Sequence[Point]]) -> Optional[Tuple[int, int]]:
    valid = sorted(k for k, v in keyframes.items() if len(v) >= 3)
    if not valid:
        return None
    return valid[0], valid[-1]


def measure_series(
    video_path: str,
    keyframes: Dict[int, Sequence[Point]],
    *,
    start: int,
    stop: int,
    step: int,
    fps: float,
    mm_per_px: float,
    snap: bool = True,
    include_profiles: bool = False,
    progress: Optional[Callable[[float], None]] = None,
    cancelled: Optional[Callable[[], bool]] = None,
) -> Tuple[List[Dict], List[Dict]]:
    """Return (series rows, profile rows). Keyframes are always included."""

    engine = AnalysisEngine()
    keys = {k for k, v in keyframes.items() if len(v) >= 3 and start <= k <= stop}
    rows: List[Dict] = []
    profiles: List[Dict] = []
    span = max(1, stop - start)
    for index, frame in iter_frames(video_path, start, stop, step, extra=keys):
        if cancelled is not None and cancelled():
            break
        measurement = measure_frame(engine, frame, keyframes, index, snap=snap)
        if measurement is None:
            continue
        rows.append(measurement_row(measurement, index, fps, mm_per_px))
        if include_profiles:
            profiles.extend(profile_rows(measurement, index, mm_per_px))
        if progress is not None:
            progress((index - start) / span)
    return rows, profiles
