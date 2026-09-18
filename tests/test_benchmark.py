import json

import numpy as np

from crater_app.core.benchmark import (
    compare_summaries,
    curve_error,
    load_labels,
    run_benchmark,
    simulated_operator_clicks,
    summarize,
)
from tests.test_analysis_regression import make_side_profile_crater_frame


def true_interface(frame_index: int) -> list:
    # Matches make_side_profile_crater_frame's surface, sampled like careful clicks.
    xs = np.arange(300, 901, 25)
    xs = xs[xs < 900]
    baseline = 205.0 + 12.0 * (xs / 899)
    phase = np.clip((xs - 475) / 300, 0, 1)
    ys = baseline + 72.0 * np.sin(np.pi * phase) ** 2
    return [[int(x), int(round(y))] for x, y in zip(xs, ys)]


def test_curve_error_is_zero_for_identical_curves_and_tracks_offsets():
    truth = [(0, 10), (100, 60), (200, 10)]
    mae, p95, coverage = curve_error(truth, truth)
    assert mae == 0.0 and p95 == 0.0 and coverage == 1.0

    shifted = [(x, y + 5) for x, y in truth]
    mae, _, _ = curve_error(shifted, truth)
    assert abs(mae - 5.0) < 1e-9


def test_simulated_clicks_are_deterministic_and_near_truth():
    truth = [(0, 100), (200, 150), (400, 100)]
    first = simulated_operator_clicks(truth, 7, 4.0, "video:10")
    assert first == simulated_operator_clicks(truth, 7, 4.0, "video:10")
    assert len(first) == 7
    mae, _, _ = curve_error(first, truth)
    assert mae < 10.0


def test_benchmark_runs_end_to_end_from_a_session_file(tmp_path):
    session = tmp_path / "gt_synthetic.json"
    session.write_text(
        json.dumps(
            {
                "video_path": "synthetic.mp4",
                "starred_frames": [],
                "guide_keyframes": {str(i): true_interface(i) for i in (10, 20, 30)},
            }
        )
    )
    labels = load_labels([session])
    assert [label.frame_index for label in labels] == [10, 20, 30]

    frame = make_side_profile_crater_frame()
    results = run_benchmark(labels, lambda _video, _index: frame.copy())
    summary = summarize(results)

    assert set(summary) == {
        "interpolation/no-snap",
        "interpolation/snap",
        "keyframe/no-snap",
        "keyframe/snap",
    }
    assert summary["keyframe/snap"]["cases"] == 3
    assert summary["interpolation/snap"]["cases"] == 1
    # On a clean synthetic edge, refinement should pull noisy clicks onto the interface.
    assert summary["keyframe/snap"]["curve_mae_px"] < summary["keyframe/no-snap"]["curve_mae_px"]
    assert summary["keyframe/snap"]["missed_rate"] == 0.0

    assert compare_summaries(summary, summary)[1].endswith("same)")
