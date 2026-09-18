from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from .auto_profile import CraterGeometry
from .settings import AnalysisSettings

Point = Tuple[float, float]

# Frames at which temporal confidence halves-ish (exp(-d / scale)). At the
# supplied 240 FPS footage this is one second away from any keyframe.
TEMPORAL_CONFIDENCE_SCALE_FRAMES = 240.0
EDGE_MIN_CONTRAST = 3.0


def densify_guide(points: Sequence[Point], x_step: int = 3) -> List[Point]:
    """Turn sparse user clicks into one left-to-right crater curve."""

    if len(points) < 2:
        return [(float(x), float(y)) for x, y in points]
    ordered = sorted((float(x), float(y)) for x, y in points)
    unique_xs: List[float] = []
    unique_ys: List[float] = []
    for x in sorted({point[0] for point in ordered}):
        ys = [point[1] for point in ordered if point[0] == x]
        unique_xs.append(x)
        unique_ys.append(float(np.mean(ys)))
    if len(unique_xs) < 2:
        return [(unique_xs[0], unique_ys[0])]
    xs = np.arange(unique_xs[0], unique_xs[-1], max(1, int(x_step)), dtype=np.float64)
    xs = np.append(xs, unique_xs[-1])
    ys = np.interp(xs, unique_xs, unique_ys)
    return [(float(x), float(y)) for x, y in zip(xs, ys)]


@dataclass
class GuideSample:
    """The operator guide that applies to one frame."""

    points: List[Point]
    source: str  # "keyframe", "interpolated" or "held"
    frames_to_key: int
    before: Optional[int]
    after: Optional[int]

    @property
    def annotation_confidence(self) -> float:
        if self.source == "keyframe":
            return 1.0
        confidence = float(np.exp(-self.frames_to_key / TEMPORAL_CONFIDENCE_SCALE_FRAMES))
        # Holding a guide past the last keyframe has no second anchor.
        return confidence * (0.7 if self.source == "held" else 1.0)


def _resample(points: Sequence[Point], samples: np.ndarray) -> np.ndarray:
    dense = np.asarray(densify_guide(points, 1), dtype=np.float64)
    source_t = np.linspace(0.0, 1.0, len(dense))
    return np.column_stack(
        (np.interp(samples, source_t, dense[:, 0]), np.interp(samples, source_t, dense[:, 1]))
    )


def guide_for_frame(
    keyframes: Dict[int, Sequence[Point]],
    frame_index: int,
    *,
    min_points: int = 3,
    samples: int = 96,
) -> Optional[GuideSample]:
    """Return the keyframe guide, or one interpolated between neighbours."""

    valid = {int(k): list(v) for k, v in keyframes.items() if len(v) >= min_points}
    if not valid:
        return None
    if frame_index in valid:
        return GuideSample(valid[frame_index], "keyframe", 0, frame_index, frame_index)
    indices = sorted(valid)
    before = max((i for i in indices if i < frame_index), default=None)
    after = min((i for i in indices if i > frame_index), default=None)
    if before is None or after is None:
        anchor = after if before is None else before
        return GuideSample(valid[anchor], "held", abs(frame_index - anchor), before, after)
    alpha = (frame_index - before) / (after - before)
    sample_t = np.linspace(0.0, 1.0, samples)
    mixed = (1.0 - alpha) * _resample(valid[before], sample_t) + alpha * _resample(
        valid[after], sample_t
    )
    return GuideSample(
        [(float(x), float(y)) for x, y in mixed],
        "interpolated",
        min(frame_index - before, after - frame_index),
        before,
        after,
    )


def interpolate_guides(
    keyframes: Dict[int, List[Point]], frame_index: int, x_step: int = 3
) -> tuple[List[Point], float, bool]:
    """Interpolate a crater curve through time between annotated keyframes.

    Returns the dense guide, temporal interpolation weight, and whether the
    requested frame is itself a user-authored keyframe.
    """

    sample = guide_for_frame(keyframes, frame_index, min_points=2)
    if sample is None:
        return [], 0.0, False
    dense = densify_guide(sample.points, x_step)
    if sample.source == "keyframe":
        return dense, 0.0, True
    if sample.source == "held":
        return dense, 1.0, False
    span = sample.after - sample.before
    alpha = (frame_index - sample.before) / span
    return dense, min(alpha, 1.0 - alpha), False


def _gray(frame: np.ndarray, settings: AnalysisSettings) -> np.ndarray:
    if frame.ndim == 2:
        return frame
    if settings.channel in (1, 2, 3):
        return frame[:, :, settings.channel - 1]
    return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)


def snap_guide_to_local_edge(
    frame: np.ndarray,
    guide: List[Point],
    settings: AnalysisSettings,
    radius_px: int = 14,
    smoothness: float = 0.6,
    blur_sigma: Tuple[float, float] = (8.0, 2.0),
) -> tuple[List[Point], float]:
    """Refine a guide onto the nearby image edge without jumping interfaces.

    A dynamic-programming path search picks one row per column inside a
    ±``radius_px`` corridor around the guide. It rewards edge strength of the
    polarity that dominates along the guide, penalises distance from the guide,
    and penalises slope changes relative to the guide, so the result is one
    continuous interface rather than a column-by-column zigzag. Rows are refined
    to sub-pixel precision. Returns the refined curve and the fraction of
    columns with a clear edge ("edge support").

    The image is blurred much more along x than y: crater interfaces are close
    to horizontal, so this averages noise along the edge without smearing its
    vertical position. Defaults were chosen on Mars Perfect Run 3 footage.
    """

    if len(guide) < 2:
        return list(guide), 0.0
    sigma_x, sigma_y = blur_sigma
    source = _gray(frame, settings)
    height, width = source.shape[:2]
    xs = np.asarray([p[0] for p in guide], dtype=np.float64)
    yp = np.asarray([p[1] for p in guide], dtype=np.float64)

    # Only the band around the guide matters; blurring the whole frame is the
    # dominant cost otherwise.
    margin_y = radius_px + int(4 * sigma_y) + 3
    margin_x = int(4 * sigma_x) + 3
    y0 = max(0, int(np.floor(yp.min())) - margin_y)
    y1 = min(height, int(np.ceil(yp.max())) + margin_y + 1)
    x0 = max(0, int(np.floor(xs.min())) - margin_x)
    x1 = min(width, int(np.ceil(xs.max())) + margin_x + 1)
    band = source[y0:y1, x0:x1].astype(np.float32)
    gray = cv2.GaussianBlur(band, (0, 0), sigmaX=sigma_x, sigmaY=sigma_y)
    dy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)

    cols = np.clip(np.round(xs).astype(int), 0, width - 1) - x0
    base = np.round(yp).astype(int)
    offsets = np.arange(-radius_px, radius_px + 1)
    rows = np.clip(base[:, None] + offsets[None, :], 0, height - 1) - y0
    g = dy[rows, cols[:, None]]

    # Material below the surface is usually darker (negative dy) but lighting
    # can invert it; follow whichever polarity dominates right at the guide.
    near = g[:, radius_px - 3 : radius_px + 4]
    polarity = -1.0 if -near[near < 0].sum() >= near[near > 0].sum() else 1.0
    edge = np.maximum(polarity * g, 0.0)
    scale = float(np.percentile(edge, 95)) + 1e-6
    strength = np.clip(edge / scale, 0.0, 1.5)

    unary = -strength + 0.35 * (offsets[None, :] / float(radius_px)) ** 2
    n, k = unary.shape
    # Transition from previous row base[i-1]+o_j to current row base[i]+o_k
    # deviates from the guide's own slope by shift[i] + (o_k - o_j).
    offset_diff = (offsets[:, None] - offsets[None, :]).astype(np.float64)
    shift = np.diff(base) - np.diff(yp)
    weight = smoothness / np.maximum(1.0, np.diff(xs))
    rows_k = np.arange(k)
    cost = unary[0].copy()
    back = np.zeros((n, k), dtype=np.int32)
    for i in range(1, n):
        trans = cost[None, :] + weight[i - 1] * np.abs(offset_diff + shift[i - 1])
        choice = np.argmin(trans, axis=1)
        back[i] = choice
        cost = unary[i] + trans[rows_k, choice]
    path = np.zeros(n, dtype=np.int32)
    path[-1] = int(np.argmin(cost))
    for i in range(n - 1, 0, -1):
        path[i - 1] = back[i, path[i]]

    ys = base + offsets[path].astype(np.float64)
    for i, j in enumerate(path):
        if 0 < j < k - 1:
            a, b, c = strength[i, j - 1], strength[i, j], strength[i, j + 1]
            denom = a - 2.0 * b + c
            if denom < -1e-6:
                ys[i] += float(np.clip(0.5 * (a - c) / denom, -0.5, 0.5))
    # The path moves in whole-row steps; a light smoothing removes the
    # resulting staircase without shifting the interface.
    if n >= 7:
        ys = cv2.GaussianBlur(ys.reshape(1, -1), (0, 0), sigmaX=3.0, borderType=cv2.BORDER_REPLICATE).ravel()
    ys = np.clip(ys, 0, height - 1)

    # Edge support: share of columns whose brightness changes by at least
    # EDGE_MIN_CONTRAST grey levels across the line, in the snapped direction.
    # On the supplied footage a visible interface gives ~6 levels, featureless
    # regions ~0.5-1.
    band_rows = np.clip(np.round(ys).astype(int) - y0, 0, gray.shape[0] - 1)
    above = np.clip(band_rows[:, None] - np.arange(2, 9)[None, :], 0, gray.shape[0] - 1)
    below = np.clip(band_rows[:, None] + np.arange(2, 9)[None, :], 0, gray.shape[0] - 1)
    col_idx = cols[:, None]
    contrast = polarity * (gray[below, col_idx].mean(axis=1) - gray[above, col_idx].mean(axis=1))
    support = float(np.mean(contrast >= EDGE_MIN_CONTRAST))
    refined = [(float(x), float(y)) for x, y in zip(xs, ys)]
    return refined, support


def geometry_from_guide(
    points: List[Point],
    evidence_confidence: float,
    is_keyframe: bool,
    annotation_confidence: Optional[float] = None,
) -> CraterGeometry | None:
    """Infer crater shoulders within a user-defined physical interface.

    Operators are encouraged to include level material on both sides of the
    crater. Those supporting wings define the undisturbed local baseline; the
    first and last clicks are therefore not automatically treated as rims.
    """

    if len(points) < 3:
        return None
    ordered = sorted(points)
    xs = np.asarray([p[0] for p in ordered], dtype=np.float64)
    ys = np.asarray([p[1] for p in ordered], dtype=np.float64)
    if xs[-1] - xs[0] < 2:
        return None
    # Smooth over roughly 10 px regardless of point spacing.
    spacing = max(1e-6, float(np.median(np.diff(xs))))
    smooth_window = int(round(21 / max(1.0, spacing / 1.0))) | 1
    smooth_window = min(smooth_window, len(ys) if len(ys) % 2 == 1 else len(ys) - 1)
    smooth_y = (
        cv2.GaussianBlur(ys.astype(np.float32).reshape(1, -1), (smooth_window, 1), 0).ravel().astype(np.float64)
        if smooth_window >= 3
        else ys.copy()
    )

    # Fit the undisturbed level from both outer wings.
    wing_count = max(3, min(len(xs) // 3, int(round(len(xs) * 0.16))))
    wing_indices = np.r_[0:wing_count, len(xs) - wing_count : len(xs)]
    slope, intercept = np.polyfit(xs[wing_indices], smooth_y[wing_indices], 1)
    wing_baseline = slope * xs + intercept
    residual = smooth_y - wing_baseline
    peak_index = int(np.argmax(residual))
    peak_depth = float(residual[peak_index])
    if peak_depth < 2.0:
        return None

    rim_threshold = max(2.0, peak_depth * 0.08)
    left = peak_index
    right = peak_index
    while left > 0 and residual[left] > rim_threshold:
        left -= 1
    while right < len(xs) - 1 and residual[right] > rim_threshold:
        right += 1

    notes: List[str] = []
    if left == 0 or right == len(xs) - 1:
        notes.append("Line does not reach flat ground on both sides; extend it past the rims.")
    wing_spread = float(np.std(residual[wing_indices]))
    if wing_spread > 0.25 * peak_depth:
        notes.append("Outer ends of the line are not level; the baseline may be off.")

    # Choose the closest return to the wing baseline around each threshold
    # crossing. This suppresses small hand-drawn wiggles on the flat shoulders.
    rim_window = max(2, int(len(xs) * 0.035))
    left_lo, left_hi = max(0, left - rim_window), min(peak_index, left + rim_window)
    right_lo, right_hi = max(peak_index, right - rim_window), min(len(xs) - 1, right + rim_window)
    left = left_lo + int(np.argmin(np.abs(residual[left_lo : left_hi + 1])))
    right = right_lo + int(np.argmin(np.abs(residual[right_lo : right_hi + 1])))
    if right - left < 3:
        return None

    crater_xs = xs[left : right + 1]
    crater_ys = smooth_y[left : right + 1]
    baseline = np.interp(
        crater_xs,
        [crater_xs[0], crater_xs[-1]],
        [wing_baseline[left], wing_baseline[right]],
    )
    depths = np.maximum(crater_ys - baseline, 0.0)
    center_local = int(np.argmax(depths))
    baseline_points = [(float(x), float(y)) for x, y in zip(crater_xs, baseline)]
    crater_points = [(float(x), float(y)) for x, y in zip(crater_xs, crater_ys)]
    if annotation_confidence is None:
        annotation_confidence = 1.0 if is_keyframe else 0.78
    confidence = float(
        np.clip(0.6 * annotation_confidence + 0.4 * evidence_confidence, 0.0, 1.0)
    )
    return CraterGeometry(
        left_rim=crater_points[0],
        center=crater_points[center_local],
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
        notes=notes,
    )
