from __future__ import annotations

from typing import Dict, List, Tuple

import cv2
import numpy as np

from .auto_profile import CraterGeometry
from .settings import AnalysisSettings

Point = Tuple[int, int]


def densify_guide(points: List[Point], x_step: int = 3) -> List[Point]:
    """Turn sparse user clicks into one left-to-right crater curve."""

    if len(points) < 2:
        return list(points)
    ordered = sorted((int(x), int(y)) for x, y in points)
    unique_xs: List[int] = []
    unique_ys: List[float] = []
    for x in sorted({point[0] for point in ordered}):
        ys = [point[1] for point in ordered if point[0] == x]
        unique_xs.append(x)
        unique_ys.append(float(np.mean(ys)))
    if len(unique_xs) < 2:
        return [(unique_xs[0], int(round(unique_ys[0])))]
    xs = np.arange(unique_xs[0], unique_xs[-1] + 1, max(1, int(x_step)))
    if xs[-1] != unique_xs[-1]:
        xs = np.append(xs, unique_xs[-1])
    ys = np.interp(xs, unique_xs, unique_ys)
    return [(int(x), int(round(y))) for x, y in zip(xs, ys)]


def interpolate_guides(
    keyframes: Dict[int, List[Point]], frame_index: int, x_step: int = 3
) -> tuple[List[Point], float, bool]:
    """Interpolate a crater curve through time between annotated keyframes.

    Returns the dense guide, temporal interpolation weight, and whether the
    requested frame is itself a user-authored keyframe.
    """

    valid = {int(k): v for k, v in keyframes.items() if len(v) >= 2}
    if not valid:
        return [], 0.0, False
    if frame_index in valid:
        return densify_guide(valid[frame_index], x_step), 0.0, True

    indices = sorted(valid)
    before = max((idx for idx in indices if idx < frame_index), default=indices[0])
    after = min((idx for idx in indices if idx > frame_index), default=indices[-1])
    if before == after:
        return densify_guide(valid[before], x_step), 1.0, False

    alpha = float((frame_index - before) / (after - before))
    sample_t = np.linspace(0.0, 1.0, 96)

    def resample(points: List[Point]) -> np.ndarray:
        dense = np.asarray(densify_guide(points, 1), dtype=np.float64)
        source_t = np.linspace(0.0, 1.0, len(dense))
        return np.column_stack(
            (
                np.interp(sample_t, source_t, dense[:, 0]),
                np.interp(sample_t, source_t, dense[:, 1]),
            )
        )

    mixed = (1.0 - alpha) * resample(valid[before]) + alpha * resample(valid[after])
    sparse = [(int(round(x)), int(round(y))) for x, y in mixed]
    return densify_guide(sparse, x_step), min(alpha, 1.0 - alpha), False


def snap_guide_to_local_edge(
    frame: np.ndarray,
    guide: List[Point],
    settings: AnalysisSettings,
    radius_px: int = 14,
) -> tuple[List[Point], float]:
    """Conservatively refine a guide without allowing it to jump interfaces."""

    if len(guide) < 2:
        return list(guide), 0.0
    if settings.channel == 1:
        gray = frame[:, :, 0]
    elif settings.channel == 2:
        gray = frame[:, :, 1]
    elif settings.channel == 3:
        gray = frame[:, :, 2]
    else:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (7, 7), 0)
    vertical_edge = np.abs(cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3))
    height, width = gray.shape
    snapped: List[Point] = []
    strengths: List[float] = []
    for x, predicted_y in guide:
        x = int(np.clip(x, 0, width - 1))
        lo = max(0, int(predicted_y) - radius_px)
        hi = min(height, int(predicted_y) + radius_px + 1)
        if hi <= lo:
            snapped.append((x, int(np.clip(predicted_y, 0, height - 1))))
            continue
        rows = np.arange(lo, hi, dtype=np.float32)
        evidence = vertical_edge[lo:hi, x]
        # The guide is authoritative: image evidence can make only a small,
        # local refinement and cannot select a different visible interface.
        score = evidence - np.abs(rows - float(predicted_y)) * 5.0
        selected = int(lo + np.argmax(score))
        snapped.append((x, selected))
        strengths.append(float(vertical_edge[selected, x]))

    ys = np.asarray([p[1] for p in snapped], dtype=np.float32)
    window = min(11, len(ys) if len(ys) % 2 == 1 else len(ys) - 1)
    if window >= 3:
        ys = cv2.GaussianBlur(ys.reshape(1, -1), (window, 1), 0).ravel()
    refined = [(point[0], int(round(y))) for point, y in zip(snapped, ys)]
    evidence_confidence = float(np.clip(np.median(strengths) / 120.0, 0.0, 1.0)) if strengths else 0.0
    return refined, evidence_confidence


def geometry_from_guide(
    points: List[Point], evidence_confidence: float, is_keyframe: bool
) -> CraterGeometry | None:
    """Measure the user-defined crater line against its endpoint baseline."""

    if len(points) < 3:
        return None
    ordered = sorted(points)
    xs = np.asarray([p[0] for p in ordered], dtype=np.float64)
    ys = np.asarray([p[1] for p in ordered], dtype=np.float64)
    if xs[-1] - xs[0] < 2:
        return None
    baseline = np.interp(xs, [xs[0], xs[-1]], [ys[0], ys[-1]])
    depths = np.maximum(ys - baseline, 0.0)
    center_index = int(np.argmax(depths))
    baseline_points = [
        (int(round(x)), int(round(y))) for x, y in zip(xs, baseline)
    ]
    crater_points = [(int(round(x)), int(round(y))) for x, y in zip(xs, ys)]
    annotation_confidence = 1.0 if is_keyframe else 0.78
    confidence = float(
        np.clip(0.75 * annotation_confidence + 0.25 * evidence_confidence, 0.0, 1.0)
    )
    return CraterGeometry(
        left_rim=crater_points[0],
        center=crater_points[center_index],
        right_rim=crater_points[-1],
        baseline_points=baseline_points,
        crater_points=crater_points,
        depth_values_px=depths.tolist(),
        profile_confidence=evidence_confidence,
        geometry_confidence=confidence,
        status=(
            "Guided keyframe — review measurement"
            if is_keyframe
            else "Guided interpolation — review measurement"
        ),
    )
