import cv2
import numpy as np

from crater_app.core.analysis import AnalysisEngine
from crater_app.core.guided_profile import densify_guide, interpolate_guides
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
        auto_surface=False,
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
        auto_surface=False,
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


def make_side_profile_crater_frame(
    width: int = 900,
    height: int = 500,
    tilt_px: float = 12.0,
) -> np.ndarray:
    """Bright air over dark material with a tilted, rimmed crater basin."""

    frame = np.full((height, width, 3), 225, dtype=np.uint8)
    xs = np.arange(width, dtype=np.float64)
    baseline = 205.0 + tilt_px * (xs / max(1, width - 1))
    left_rim_x, center_x, right_rim_x = 475, 625, 775
    surface = baseline.copy()
    inside = (xs >= left_rim_x) & (xs <= right_rim_x)
    phase = (xs[inside] - left_rim_x) / (right_rim_x - left_rim_x)
    surface[inside] += 72.0 * np.sin(np.pi * phase) ** 2
    surface -= 7.0 * np.exp(-((xs - left_rim_x) / 24.0) ** 2)
    surface -= 6.0 * np.exp(-((xs - right_rim_x) / 24.0) ** 2)
    polygon = np.column_stack((xs.astype(np.int32), surface.astype(np.int32)))
    polygon = np.vstack(
        (
            polygon,
            np.asarray([[width - 1, height - 1], [0, height - 1]], dtype=np.int32),
        )
    )
    cv2.fillPoly(frame, [polygon], (58, 54, 60))
    noise = np.random.default_rng(42).normal(0, 2.0, frame.shape).astype(np.int16)
    return np.clip(frame.astype(np.int16) + noise, 0, 255).astype(np.uint8)


def test_automatic_side_profile_recovers_rims_depth_and_tilt():
    engine = AnalysisEngine()
    frame = make_side_profile_crater_frame()
    result = engine.analyze_frame(
        frame,
        AnalysisSettings(
            auto_surface=True,
            left_margin=50,
            right_margin=50,
            x_step=3,
            real_width_mm=180.0,
        ),
    )

    assert result.detection_mode == "automatic"
    assert result.geometry is not None
    assert 400 <= result.geometry.left_rim[0] <= 570
    assert 690 <= result.geometry.right_rim[0] <= 820
    assert 45.0 <= result.metrics.max_crater_depth_px <= 90.0
    assert 180.0 <= result.metrics.max_crater_width_px <= 420.0
    assert result.metrics.crater_area_px > 5_000.0
    assert result.metrics.confidence >= 0.35
    assert 0.0 <= result.metrics.baseline_tilt_degrees <= 3.0


def test_automatic_profile_is_deterministic():
    engine = AnalysisEngine()
    frame = make_side_profile_crater_frame()
    settings = AnalysisSettings(auto_surface=True, x_step=4)
    first = engine.analyze_frame(frame.copy(), settings)
    second = engine.analyze_frame(frame.copy(), settings)

    assert first.profile_points == second.profile_points
    assert first.metrics.to_dict() == second.metrics.to_dict()
    assert np.array_equal(first.solid_mask, second.solid_mask)


def test_low_visibility_trace_rejects_narrow_reflection_spikes():
    frame = make_side_profile_crater_frame()
    haze = np.full_like(frame, 205)
    frame = cv2.addWeighted(frame, 0.48, haze, 0.52, 0.0)
    # Static glass reflections/scratches should not become crater walls.
    cv2.rectangle(frame, (265, 110), (276, 345), (92, 92, 92), thickness=-1)
    cv2.rectangle(frame, (350, 100), (359, 330), (238, 238, 238), thickness=-1)

    result = AnalysisEngine().analyze_frame(
        frame,
        AnalysisSettings(
            auto_surface=True,
            left_margin=50,
            right_margin=50,
            x_step=3,
        ),
    )

    assert result.geometry is not None
    assert 540 <= result.geometry.center[0] <= 710
    assert result.geometry.left_rim[0] > 390
    assert result.geometry.right_rim[0] < 830
    assert result.metrics.max_crater_width_px > result.metrics.max_crater_depth_px


def test_automatic_mode_does_not_measure_a_flat_surface():
    frame = np.full((420, 840, 3), 225, dtype=np.uint8)
    cv2.rectangle(frame, (0, 205), (839, 419), (58, 55, 60), thickness=-1)
    result = AnalysisEngine().analyze_frame(
        frame,
        AnalysisSettings(
            auto_surface=True,
            left_margin=50,
            right_margin=50,
            x_step=3,
        ),
    )

    assert result.geometry is None
    assert result.metrics.confidence == 0.0
    assert result.metrics.max_crater_depth_px == 0.0


def test_sparse_operator_clicks_define_guided_crater_geometry():
    frame = make_side_profile_crater_frame()
    clicks = [(470, 205), (560, 246), (625, 278), (700, 248), (780, 215)]
    result = AnalysisEngine().analyze_guided_frame(
        frame,
        AnalysisSettings(auto_surface=True, x_step=3),
        clicks,
        is_keyframe=True,
        snap_to_edge=False,
    )

    assert result.detection_mode == "guided"
    assert result.geometry is not None
    assert result.geometry.left_rim[0] == 470
    assert result.geometry.right_rim[0] == 780
    assert 55.0 <= result.metrics.max_crater_depth_px <= 75.0
    assert result.metrics.max_crater_width_px == 310.0
    assert result.status.startswith("Guided keyframe")


def test_guides_fill_click_gaps_and_interpolate_between_frames():
    keyframes = {
        10: [(100, 150), (200, 210), (300, 150)],
        30: [(120, 160), (220, 240), (320, 160)],
    }
    curve, temporal_distance, is_keyframe = interpolate_guides(keyframes, 20, 4)

    assert not is_keyframe
    assert temporal_distance == 0.5
    assert curve[0] == (110, 155)
    assert curve[-1] == (310, 155)
    assert max(y for _, y in curve) >= 220
    assert len(curve) > len(keyframes[10])

    dense = densify_guide([(30, 100), (50, 120), (70, 100)], 2)
    assert dense[0] == (30, 100)
    assert dense[-1] == (70, 100)
    assert len(dense) == 21
