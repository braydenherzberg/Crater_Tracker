import cv2
import numpy as np

from crater_app.core.analysis import AnalysisEngine
from crater_app.core.settings import AnalysisSettings


def make_synthetic_crater_frame(width: int = 640, height: int = 360) -> np.ndarray:
    frame = np.full((height, width, 3), 220, dtype=np.uint8)
    surface_y = 190
    cv2.rectangle(frame, (0, surface_y), (width - 1, height - 1), (80, 80, 80), thickness=-1)
    center_x = width // 2
    cv2.ellipse(frame, (center_x, surface_y), (90, 45), 0, 0, 180, (30, 30, 30), thickness=-1)
    cv2.GaussianBlur(frame, (5, 5), 0, dst=frame)
    return frame


def test_analysis_is_deterministic_for_same_input():
    engine = AnalysisEngine()
    frame = make_synthetic_crater_frame()
    settings = AnalysisSettings(
        threshold=100,
        smoothing=11,
        despeckle=5,
        channel=0,
        zone_left=160,
        zone_right=160,
        surface_boundary=190,
        scan_mode=1,
    )
    result_a = engine.analyze_frame(frame.copy(), settings)
    result_b = engine.analyze_frame(frame.copy(), settings)

    assert np.array_equal(result_a.solid_mask, result_b.solid_mask)
    assert result_a.profile_points == result_b.profile_points
    assert result_a.metrics.to_dict() == result_b.metrics.to_dict()


def test_synthetic_frame_produces_expected_crater_shape_metrics():
    engine = AnalysisEngine()
    frame = make_synthetic_crater_frame()
    settings = AnalysisSettings(
        threshold=100,
        smoothing=11,
        despeckle=5,
        channel=0,
        zone_left=170,
        zone_right=170,
        surface_boundary=190,
        scan_mode=1,
    )

    result = engine.analyze_frame(frame, settings)
    metrics = result.metrics

    assert metrics.point_count > 30
    assert 120.0 <= metrics.width_px <= 420.0
    assert 1.0 <= metrics.depth_px <= 140.0
    assert metrics.area_px2 > 100.0
    assert 0.25 <= metrics.confidence <= 1.0

