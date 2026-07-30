from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

import cv2
import numpy as np

from .auto_profile import CraterGeometry, extract_auto_profile
from .crater_profile import extract_profile_points
from .metrics import CraterMetrics, compute_geometry_metrics, compute_metrics
from .preprocess import build_solid_mask, rotate_frame, select_channel
from .settings import AnalysisSettings


@dataclass
class AnalysisResult:
    frame: np.ndarray
    solid_mask: np.ndarray
    profile_points: List[Tuple[int, int]]
    metrics: CraterMetrics
    geometry: CraterGeometry | None = None
    detection_mode: str = "manual"
    status: str = "Manual profile"


class AnalysisEngine:
    """Deterministic frame analysis for a given settings object."""

    def __init__(self) -> None:
        self._clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))

    def analyze_frame(self, frame: np.ndarray, settings: AnalysisSettings) -> AnalysisResult:
        h = frame.shape[0]
        normalized = settings.normalized(h)
        rotated = rotate_frame(frame, normalized.tilt_degrees)
        if normalized.auto_surface:
            auto = extract_auto_profile(rotated, normalized)
            if auto.geometry is None:
                metrics = compute_metrics([], normalized.surface_boundary)
                status = "No reliable crater candidate found"
            else:
                metrics = compute_geometry_metrics(
                    auto.geometry.crater_points,
                    auto.geometry.baseline_points,
                    auto.geometry.geometry_confidence,
                )
                status = auto.geometry.status
            return AnalysisResult(
                frame=rotated,
                solid_mask=auto.solid_mask,
                profile_points=auto.profile_points,
                metrics=metrics,
                geometry=auto.geometry,
                detection_mode="automatic",
                status=status,
            )

        gray = select_channel(rotated, normalized.channel)
        solid_mask = build_solid_mask(gray, normalized.threshold, self._clahe)
        profile_points = extract_profile_points(solid_mask, normalized)
        metrics = compute_metrics(profile_points, normalized.surface_boundary)
        return AnalysisResult(
            frame=rotated,
            solid_mask=solid_mask,
            profile_points=profile_points,
            metrics=metrics,
            detection_mode="manual",
            status="Manual profile",
        )
