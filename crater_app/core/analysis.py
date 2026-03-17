from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

import cv2
import numpy as np

from .crater_profile import extract_profile_points
from .metrics import CraterMetrics, compute_metrics
from .preprocess import build_solid_mask, rotate_frame, select_channel
from .settings import AnalysisSettings


@dataclass
class AnalysisResult:
    frame: np.ndarray
    solid_mask: np.ndarray
    profile_points: List[Tuple[int, int]]
    metrics: CraterMetrics


class AnalysisEngine:
    """Deterministic frame analysis for a given settings object."""

    def __init__(self) -> None:
        self._clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))

    def analyze_frame(self, frame: np.ndarray, settings: AnalysisSettings) -> AnalysisResult:
        h = frame.shape[0]
        normalized = settings.normalized(h)
        rotated = rotate_frame(frame, normalized.tilt_degrees)
        gray = select_channel(rotated, normalized.channel)
        solid_mask = build_solid_mask(gray, normalized.threshold, self._clahe)
        profile_points = extract_profile_points(solid_mask, normalized)
        metrics = compute_metrics(profile_points, normalized.surface_boundary)
        return AnalysisResult(
            frame=rotated,
            solid_mask=solid_mask,
            profile_points=profile_points,
            metrics=metrics,
        )

