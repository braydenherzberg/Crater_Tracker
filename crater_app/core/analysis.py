from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

import cv2
import numpy as np

from .auto_profile import CraterGeometry, extract_auto_profile
from .crater_profile import extract_profile_points
from .guided_profile import densify_guide, geometry_from_guide, snap_guide_to_local_edge
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

    def analyze_guided_frame(
        self,
        frame: np.ndarray,
        settings: AnalysisSettings,
        guide_points: List[Tuple[int, int]],
        *,
        is_keyframe: bool,
        snap_to_edge: bool = True,
        annotation_confidence: float | None = None,
    ) -> AnalysisResult:
        """Analyze only the crater interface supplied by the operator."""

        normalized = settings.normalized(frame.shape[0])
        rotated = rotate_frame(frame, normalized.tilt_degrees)
        # One column per pixel: the rims and depth are then not quantised to
        # the coarser x_step used by the legacy detectors.
        dense_guide = densify_guide(guide_points, 1)
        if snap_to_edge:
            profile, evidence = snap_guide_to_local_edge(
                rotated, dense_guide, normalized
            )
        else:
            profile, evidence = dense_guide, 0.0
        geometry = geometry_from_guide(
            profile, evidence, is_keyframe, annotation_confidence
        )
        if geometry is None:
            metrics = compute_metrics([], normalized.surface_boundary)
            mask = np.zeros(rotated.shape[:2], dtype=np.uint8)
            status = "Add at least three points along the crater line"
        else:
            metrics = compute_geometry_metrics(
                geometry.crater_points,
                geometry.baseline_points,
                geometry.geometry_confidence,
            )
            mask = np.zeros(rotated.shape[:2], dtype=np.uint8)
            status = geometry.status
        return AnalysisResult(
            frame=rotated,
            solid_mask=mask,
            profile_points=profile,
            metrics=metrics,
            geometry=geometry,
            detection_mode="guided",
            status=status,
        )
