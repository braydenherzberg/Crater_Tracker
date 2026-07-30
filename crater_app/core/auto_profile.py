from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

import cv2
import numpy as np

from .settings import AnalysisSettings


@dataclass
class CraterGeometry:
    """Automatically inferred side-profile crater geometry."""

    left_rim: Tuple[int, int]
    center: Tuple[int, int]
    right_rim: Tuple[int, int]
    baseline_points: List[Tuple[int, int]]
    crater_points: List[Tuple[int, int]]
    depth_values_px: List[float]
    profile_confidence: float
    geometry_confidence: float
    status: str


@dataclass
class AutoProfileResult:
    profile_points: List[Tuple[int, int]]
    solid_mask: np.ndarray
    geometry: Optional[CraterGeometry]
    edge_confidence: float


def _odd(value: int, minimum: int = 3) -> int:
    value = max(minimum, int(value))
    return value if value % 2 == 1 else value + 1


def _smooth_1d(values: np.ndarray, window: int) -> np.ndarray:
    if len(values) < 3:
        return values.astype(np.float64)
    kernel = min(_odd(window), _odd(len(values) - 1))
    return cv2.GaussianBlur(
        values.astype(np.float32).reshape(1, -1),
        (kernel, 1),
        0,
    ).ravel().astype(np.float64)


def _rolling_median(values: np.ndarray, window: int) -> np.ndarray:
    if len(values) < 3:
        return values.astype(np.float64)
    window = min(_odd(window), _odd(len(values) - 1))
    pad = window // 2
    padded = np.pad(values, (pad, pad), mode="edge")
    windows = np.lib.stride_tricks.sliding_window_view(padded, window)
    return np.median(windows, axis=1)


def _analysis_channel(frame: np.ndarray, channel: int) -> np.ndarray:
    if channel == 1:
        return frame[:, :, 0]
    if channel == 2:
        return frame[:, :, 1]
    if channel == 3:
        return frame[:, :, 2]
    return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)


def _build_profile_mask(shape: Tuple[int, int], points: List[Tuple[int, int]]) -> np.ndarray:
    height, width = shape
    mask = np.zeros((height, width), dtype=np.uint8)
    if len(points) < 2:
        return mask
    polygon = [(points[0][0], height - 1), *points, (points[-1][0], height - 1)]
    cv2.fillPoly(mask, [np.asarray(polygon, dtype=np.int32)], 255)
    return mask


def _find_crater_geometry(
    points: List[Tuple[int, int]],
    edge_confidence: float,
    settings: AnalysisSettings,
) -> Optional[CraterGeometry]:
    if len(points) < 24:
        return None

    xs = np.asarray([p[0] for p in points], dtype=np.float64)
    ys = np.asarray([p[1] for p in points], dtype=np.float64)
    count = len(points)
    fine = _smooth_1d(ys, max(5, int(count * 0.025)))

    # A 1-D morphological opening estimates the surface with basin-like
    # downward excursions removed. In image coordinates, a crater depression
    # is a positive y excursion.
    opening_width = _odd(
        int(count * float(np.clip(settings.auto_max_crater_width_fraction, 0.12, 0.70))),
        minimum=15,
    )
    opening_width = min(opening_width, _odd(count - 1, minimum=3))
    opened = cv2.morphologyEx(
        fine.astype(np.float32).reshape(1, -1),
        cv2.MORPH_OPEN,
        np.ones((1, opening_width), dtype=np.uint8),
    ).ravel().astype(np.float64)
    residual = _smooth_1d(np.maximum(fine - opened, 0.0), max(5, int(count * 0.02)))

    # Keep candidate rims well inside the tracked span. Transparent container
    # walls create strong vertical steps near both sides and must never serve
    # as a physical crater rim.
    edge = max(2, int(count * 0.08))
    searchable = residual.copy()
    searchable[:edge] = 0.0
    searchable[-edge:] = 0.0
    peak_index = int(np.argmax(searchable))
    peak_signal = float(searchable[peak_index])
    if peak_signal < 1.0:
        return None

    derivative_noise = float(
        1.4826 * np.median(np.abs(np.diff(fine) - np.median(np.diff(fine))))
    )
    threshold = max(1.5, peak_signal * 0.12, derivative_noise * 2.5)
    left = peak_index
    right = peak_index
    while left > edge and residual[left] > threshold:
        left -= 1
    while right < count - edge - 1 and residual[right] > threshold:
        right += 1

    # Refine the threshold crossings to nearby local high points (small y),
    # which are the physical crater rims in image coordinates.
    rim_window = max(3, int(count * 0.12))
    left_lo = max(edge, left - rim_window)
    left_hi = min(peak_index - 1, left + rim_window)
    right_lo = max(peak_index + 1, right - rim_window)
    right_hi = min(count - edge - 1, right + rim_window)
    if left_hi <= left_lo or right_hi <= right_lo:
        return None
    left = left_lo + int(np.argmin(fine[left_lo : left_hi + 1]))
    right = right_lo + int(np.argmin(fine[right_lo : right_hi + 1]))
    if right - left < max(5, int(count * settings.auto_min_crater_width_fraction)):
        return None

    baseline = np.interp(
        np.arange(left, right + 1),
        [left, right],
        [fine[left], fine[right]],
    )
    depths = fine[left : right + 1] - baseline
    positive_depths = np.maximum(depths, 0.0)
    center_local = int(np.argmax(positive_depths))
    center_index = left + center_local
    max_depth = float(positive_depths[center_local])
    width = float(xs[right] - xs[left])
    if max_depth < 1.0 or width <= 0.0:
        return None

    continuity = float(np.clip(1.0 - np.mean(np.abs(np.diff(fine))) / 8.0, 0.0, 1.0))
    noise_signal = float(
        np.clip(max_depth / max(8.0, derivative_noise * 8.0), 0.0, 1.0)
    )
    scale_signal = float(np.clip(max_depth / 25.0, 0.0, 1.0))
    depth_signal = min(noise_signal, scale_signal)
    basin_fill = float(np.mean(positive_depths > max(1.0, max_depth * 0.10)))
    edge_clearance = float(
        np.clip(min(left - edge, count - edge - right) / max(1.0, count * 0.10), 0.0, 1.0)
    )
    geometry_confidence = float(
        np.clip(
            (0.48 * depth_signal)
            + (0.16 * basin_fill)
            + (0.12 * continuity)
            + (0.12 * edge_clearance)
            + (0.12 * edge_confidence),
            0.0,
            1.0,
        )
    )
    width_depth_ratio = width / max(1.0, max_depth)
    aspect_plausibility = float(
        np.clip((width_depth_ratio - 0.75) / 0.75, 0.0, 1.0)
    )
    geometry_confidence *= 0.30 + (0.70 * aspect_plausibility)
    baseline_tilt_degrees = float(
        np.degrees(
            np.arctan2(float(fine[right] - fine[left]), max(1.0, width))
        )
    )
    tilt_plausibility = float(
        np.clip(1.0 - max(0.0, abs(baseline_tilt_degrees) - 8.0) / 20.0, 0.0, 1.0)
    )
    geometry_confidence *= 0.25 + (0.75 * tilt_plausibility)
    geometry_confidence *= 0.30 + (0.70 * edge_confidence)
    if geometry_confidence >= 0.72:
        status = "Strong crater candidate"
    elif geometry_confidence >= 0.42:
        status = "Candidate — review suggested"
    else:
        status = "Weak candidate"

    baseline_points = [
        (int(round(xs[i])), int(round(baseline[i - left])))
        for i in range(left, right + 1)
    ]
    crater_points = [
        (int(round(xs[i])), int(round(fine[i])))
        for i in range(left, right + 1)
    ]
    return CraterGeometry(
        left_rim=crater_points[0],
        center=crater_points[center_local],
        right_rim=crater_points[-1],
        baseline_points=baseline_points,
        crater_points=crater_points,
        depth_values_px=positive_depths.tolist(),
        profile_confidence=edge_confidence,
        geometry_confidence=geometry_confidence,
        status=status,
    )


def extract_auto_profile(
    frame: np.ndarray,
    settings: AnalysisSettings,
) -> AutoProfileResult:
    """Trace a bright-background/dark-material side profile automatically.

    The analysis is performed on a bounded working resolution and mapped back
    to source pixels. It favors a sustained bright-to-dark transition and uses
    a robust two-pass column tracker to reject glare and wall markings.
    """

    source_h, source_w = frame.shape[:2]
    working_scale = min(1.0, settings.auto_working_width_px / max(1, source_w))
    working_w = max(32, int(round(source_w * working_scale)))
    working_h = max(24, int(round(source_h * working_scale)))
    working = (
        frame
        if working_scale == 1.0
        else cv2.resize(frame, (working_w, working_h), interpolation=cv2.INTER_AREA)
    )
    gray = _analysis_channel(working, settings.channel)
    gray = cv2.GaussianBlur(gray, (9, 9), 0)

    contrast_window = _odd(max(7, int(working_h * 0.025)))
    gray_f = gray.astype(np.float32)
    above = cv2.boxFilter(
        gray_f, -1, (1, contrast_window), anchor=(0, contrast_window - 1)
    )
    below = cv2.boxFilter(gray_f, -1, (1, contrast_window), anchor=(0, 0))
    response = above - below

    search_top = int(working_h * settings.auto_search_top_fraction)
    search_bottom = int(working_h * settings.auto_search_bottom_fraction)
    search_top = max(0, min(working_h - 2, search_top))
    search_bottom = max(search_top + 2, min(working_h, search_bottom))

    raw_y = np.argmax(response[search_top:search_bottom], axis=0) + search_top
    median_window = _odd(max(11, int(working_w * 0.055)))
    guide_y = _rolling_median(raw_y, median_window)
    search_radius = max(10, int(working_h * 0.10))

    picked_y = np.empty(working_w, dtype=np.float64)
    picked_score = np.empty(working_w, dtype=np.float64)
    for x, center in enumerate(guide_y.astype(int)):
        lo = max(search_top, center - search_radius)
        hi = min(search_bottom, center + search_radius + 1)
        rows = np.arange(lo, hi, dtype=np.float32)
        local_scores = response[lo:hi, x] - (
            np.abs(rows - float(center)) * 0.65
        )
        local_index = int(np.argmax(local_scores))
        picked_y[x] = lo + local_index
        picked_score[x] = response[lo + local_index, x]

    local_median = _rolling_median(
        picked_y, max(9, int(working_w * 0.035))
    )
    outlier_limit = max(5.0, working_h * 0.018)
    picked_y = np.where(
        np.abs(picked_y - local_median) > outlier_limit,
        local_median,
        picked_y,
    )
    picked_y = _smooth_1d(picked_y, max(7, int(working_w * 0.035)))
    score_low, score_high = np.percentile(picked_score, [15, 85])
    edge_confidence = float(
        np.clip((float(np.median(picked_score)) - score_low) / max(8.0, score_high - score_low), 0.0, 1.0)
    )

    x_start = max(0, settings.left_margin)
    x_stop = max(x_start + 1, source_w - max(0, settings.right_margin))
    xs = np.arange(x_start, x_stop, max(1, settings.x_step), dtype=int)
    working_xs = np.clip(
        np.rint(xs * working_scale).astype(int),
        0,
        working_w - 1,
    )
    ys = np.clip(
        np.rint(picked_y[working_xs] / working_scale).astype(int),
        0,
        source_h - 1,
    )
    points = list(zip(xs.tolist(), ys.tolist()))
    mask = _build_profile_mask((source_h, source_w), points)
    geometry = _find_crater_geometry(points, edge_confidence, settings)
    return AutoProfileResult(
        profile_points=points,
        solid_mask=mask,
        geometry=geometry,
        edge_confidence=edge_confidence,
    )
