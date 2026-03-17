from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import List, Tuple

import numpy as np


@dataclass
class CraterMetrics:
    point_count: int
    avg_crater_width_px: float
    max_crater_width_px: float
    trace_width_px: float
    max_crater_depth_px: float
    crater_area_px: float
    confidence: float

    def to_dict(self) -> dict:
        return asdict(self)


def compute_metrics(
    points: List[Tuple[int, int]],
    surface_boundary: int,
) -> CraterMetrics:
    if len(points) < 2:
        return CraterMetrics(
            point_count=len(points),
            avg_crater_width_px=0.0,
            max_crater_width_px=0.0,
            trace_width_px=0.0,
            max_crater_depth_px=0.0,
            crater_area_px=0.0,
            confidence=0.0,
        )

    xs = np.array([p[0] for p in points], dtype=np.float64)
    ys = np.array([p[1] for p in points], dtype=np.float64)
    trace_width_px = float(xs.max() - xs.min())
    y_from_surface = ys - float(surface_boundary)
    max_crater_depth_px = float(max(0.0, y_from_surface.max()))

    # Area between the profile trace and the surface boundary (treated as y=0).
    order = np.argsort(xs)
    crater_area_px = float(np.trapezoid(np.abs(y_from_surface[order]), xs[order]))
    # Average crater width estimate across depth levels (area/depth).
    avg_crater_width_px = float(crater_area_px / max_crater_depth_px) if max_crater_depth_px > 1e-9 else 0.0

    # Rim-based max crater width: span where profile is at least 5% below surface.
    depth = np.maximum(0.0, y_from_surface)
    rim_fraction = 0.05
    depth_threshold = max_crater_depth_px * rim_fraction
    crater_mask = depth >= depth_threshold
    if np.any(crater_mask):
        crater_x = xs[crater_mask]
        max_crater_width_px = float(crater_x.max() - crater_x.min())
    else:
        max_crater_width_px = 0.0

    # Confidence combines enough points + continuity + non-flat profile.
    diffs = np.abs(np.diff(ys))
    continuity = 1.0 if len(diffs) == 0 else float(np.clip(1.0 - np.mean(diffs) / 20.0, 0.0, 1.0))
    richness = float(np.clip(len(points) / 120.0, 0.0, 1.0))
    shape_strength = float(np.clip(max_crater_depth_px / 50.0, 0.0, 1.0))
    confidence = float(np.clip((continuity * 0.5) + (richness * 0.25) + (shape_strength * 0.25), 0.0, 1.0))

    return CraterMetrics(
        point_count=len(points),
        avg_crater_width_px=avg_crater_width_px,
        max_crater_width_px=max_crater_width_px,
        trace_width_px=trace_width_px,
        max_crater_depth_px=max_crater_depth_px,
        crater_area_px=crater_area_px,
        confidence=confidence,
    )

