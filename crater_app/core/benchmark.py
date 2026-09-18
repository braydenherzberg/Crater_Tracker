"""Score guided crater tracking against operator-labeled ground truth.

Ground truth is any saved session whose guide keyframes were drawn carefully
along the physical crater interface. Each labeled frame is used in two ways:

* ``keyframe``: simulate a quick, imprecise operator (a few noisy clicks near
  the true line), run guided analysis, and measure how far the result lands
  from the careful label. This isolates edge refinement.
* ``interpolation``: hide one labeled frame, rebuild it from the neighbouring
  labels exactly as the app interpolates between keyframes, and compare. This
  measures tracking between keyframes.

Both run with edge snapping on and off so the value of refinement is visible.
Errors are in source-frame pixels; lower is better.
"""

from __future__ import annotations

import json
import zlib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

import numpy as np

from .analysis import AnalysisEngine, AnalysisResult
from .guided_profile import densify_guide, interpolate_guides
from .settings import AnalysisSettings

Point = Tuple[int, int]
FrameLoader = Callable[[str, int], Optional[np.ndarray]]

# Summary fields where a smaller value is better, used by compare_summaries.
LOWER_IS_BETTER = (
    "curve_mae_px",
    "curve_p95_px",
    "width_abs_err_px",
    "depth_abs_err_px",
    "rim_abs_err_px",
    "missed_rate",
)


@dataclass
class LabeledFrame:
    video_path: str
    frame_index: int
    points: List[Point]
    source: str


@dataclass
class CaseResult:
    experiment: str
    snap: bool
    video: str
    frame_index: int
    curve_mae_px: float
    curve_p95_px: float
    coverage: float
    width_abs_err_px: float
    depth_abs_err_px: float
    rim_abs_err_px: float
    missed: bool
    confidence: float
    source: str


def load_labels(session_paths: Iterable[Path]) -> List[LabeledFrame]:
    labels: List[LabeledFrame] = []
    for path in session_paths:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        video_path = str(payload.get("video_path") or "")
        for frame_index, points in payload.get("guide_keyframes", {}).items():
            if not isinstance(points, list) or len(points) < 3:
                continue
            labels.append(
                LabeledFrame(
                    video_path=video_path,
                    frame_index=int(frame_index),
                    points=[(int(p[0]), int(p[1])) for p in points],
                    source=Path(path).name,
                )
            )
    labels.sort(key=lambda label: (label.video_path, label.frame_index))
    return labels


def curve_error(predicted: List[Point], truth: List[Point]) -> Tuple[float, float, float]:
    """Vertical error of a predicted curve against a labeled curve.

    Returns mean absolute error, 95th-percentile error, and the fraction of the
    labeled horizontal span that the prediction covers.
    """

    gt = np.asarray(densify_guide(truth, 1), dtype=np.float64)
    if len(gt) < 2 or not predicted:
        return float("nan"), float("nan"), 0.0
    pred = np.asarray(sorted(predicted), dtype=np.float64)
    inside = (pred[:, 0] >= gt[0, 0]) & (pred[:, 0] <= gt[-1, 0])
    if not np.any(inside):
        return float("nan"), float("nan"), 0.0
    errors = np.abs(pred[inside, 1] - np.interp(pred[inside, 0], gt[:, 0], gt[:, 1]))
    span = gt[-1, 0] - gt[0, 0]
    covered = pred[inside, 0].max() - pred[inside, 0].min()
    return (
        float(errors.mean()),
        float(np.percentile(errors, 95)),
        float(np.clip(covered / span, 0.0, 1.0)) if span > 0 else 0.0,
    )


def simulated_operator_clicks(
    truth: List[Point], clicks: int, noise_px: float, seed_key: str
) -> List[Point]:
    """A few evenly spaced clicks near the labeled line with vertical noise."""

    gt = np.asarray(densify_guide(truth, 1), dtype=np.float64)
    rng = np.random.default_rng(zlib.crc32(seed_key.encode("utf-8")))
    xs = np.linspace(gt[0, 0], gt[-1, 0], max(3, clicks))
    ys = np.interp(xs, gt[:, 0], gt[:, 1]) + rng.normal(0.0, noise_px, len(xs))
    return [(int(round(x)), int(round(y))) for x, y in zip(xs, ys)]


def _score(
    experiment: str,
    snap: bool,
    label: LabeledFrame,
    predicted: AnalysisResult,
    reference: AnalysisResult,
) -> CaseResult:
    mae, p95, coverage = curve_error(predicted.profile_points, label.points)
    ref_geo, pred_geo = reference.geometry, predicted.geometry
    missed = ref_geo is not None and pred_geo is None
    if ref_geo is not None and pred_geo is not None:
        width_err = abs(predicted.metrics.max_crater_width_px - reference.metrics.max_crater_width_px)
        depth_err = abs(predicted.metrics.max_crater_depth_px - reference.metrics.max_crater_depth_px)
        rim_err = 0.5 * (
            abs(pred_geo.left_rim[0] - ref_geo.left_rim[0])
            + abs(pred_geo.right_rim[0] - ref_geo.right_rim[0])
        )
    else:
        width_err = depth_err = rim_err = float("nan")
    return CaseResult(
        experiment=experiment,
        snap=snap,
        video=Path(label.video_path).name,
        frame_index=label.frame_index,
        curve_mae_px=mae,
        curve_p95_px=p95,
        coverage=coverage,
        width_abs_err_px=width_err,
        depth_abs_err_px=depth_err,
        rim_abs_err_px=rim_err,
        missed=missed,
        confidence=float(predicted.metrics.confidence),
        source=label.source,
    )


def run_benchmark(
    labels: List[LabeledFrame],
    load_frame: FrameLoader,
    *,
    settings: Optional[AnalysisSettings] = None,
    clicks: int = 7,
    noise_px: float = 4.0,
    progress: Optional[Callable[[str], None]] = None,
) -> List[CaseResult]:
    settings = settings or AnalysisSettings(x_step=3)
    engine = AnalysisEngine()
    results: List[CaseResult] = []

    by_video: Dict[str, List[LabeledFrame]] = {}
    for label in labels:
        by_video.setdefault(label.video_path, []).append(label)

    def seed(label: LabeledFrame) -> str:
        return f"{Path(label.video_path).name}:{label.frame_index}"

    for video_path, video_labels in by_video.items():
        for position, label in enumerate(video_labels):
            if progress:
                progress(f"{Path(video_path).name} frame {label.frame_index:,}")
            frame = load_frame(video_path, label.frame_index)
            if frame is None:
                if progress:
                    progress(f"  skipped: could not read frame from {video_path}")
                continue
            reference = engine.analyze_guided_frame(
                frame, settings, label.points, is_keyframe=True, snap_to_edge=False
            )

            operator = simulated_operator_clicks(label.points, clicks, noise_px, seed(label))
            for snap in (False, True):
                predicted = engine.analyze_guided_frame(
                    frame, settings, operator, is_keyframe=True, snap_to_edge=snap
                )
                results.append(_score("keyframe", snap, label, predicted, reference))

            # Leave this label out and rebuild it from its neighbours, which
            # stand in for operator keyframes drawn elsewhere in the run.
            if 0 < position < len(video_labels) - 1:
                keyframes = {
                    other.frame_index: simulated_operator_clicks(
                        other.points, clicks, noise_px, seed(other)
                    )
                    for other in video_labels
                    if other is not label
                }
                guide, _, _ = interpolate_guides(keyframes, label.frame_index, settings.x_step)
                for snap in (False, True):
                    predicted = engine.analyze_guided_frame(
                        frame, settings, guide, is_keyframe=False, snap_to_edge=snap
                    )
                    results.append(_score("interpolation", snap, label, predicted, reference))
    return results


def summarize(results: List[CaseResult]) -> Dict[str, Dict[str, float]]:
    summary: Dict[str, Dict[str, float]] = {}
    groups: Dict[str, List[CaseResult]] = {}
    for result in results:
        key = f"{result.experiment}/{'snap' if result.snap else 'no-snap'}"
        groups.setdefault(key, []).append(result)
    for key in sorted(groups):
        rows = groups[key]

        def mean(field: str) -> float:
            values = np.asarray([getattr(r, field) for r in rows], dtype=np.float64)
            values = values[np.isfinite(values)]
            return float(values.mean()) if len(values) else float("nan")

        summary[key] = {
            "cases": float(len(rows)),
            "curve_mae_px": mean("curve_mae_px"),
            "curve_p95_px": mean("curve_p95_px"),
            "width_abs_err_px": mean("width_abs_err_px"),
            "depth_abs_err_px": mean("depth_abs_err_px"),
            "rim_abs_err_px": mean("rim_abs_err_px"),
            "missed_rate": float(np.mean([r.missed for r in rows])),
            "mean_confidence": mean("confidence"),
        }
    return summary


def compare_summaries(
    current: Dict[str, Dict[str, float]], baseline: Dict[str, Dict[str, float]]
) -> List[str]:
    lines: List[str] = []
    for group, metrics in current.items():
        base = baseline.get(group)
        if base is None:
            continue
        lines.append(group)
        for field in LOWER_IS_BETTER:
            new, old = metrics.get(field, float("nan")), base.get(field, float("nan"))
            if not (np.isfinite(new) and np.isfinite(old)):
                continue
            delta = new - old
            verdict = "same" if abs(delta) < 0.05 else ("better" if delta < 0 else "WORSE")
            lines.append(f"  {field:<18} {old:8.2f} -> {new:8.2f}  ({delta:+.2f}, {verdict})")
    return lines


def results_as_rows(results: List[CaseResult]) -> List[Dict]:
    return [asdict(result) for result in results]
