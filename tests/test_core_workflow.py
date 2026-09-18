import csv
import json

import cv2
import numpy as np
import pytest

from crater_app import cli_batch
from crater_app.core.activity import analyze_activity
from crater_app.core.guided_profile import guide_for_frame, snap_guide_to_local_edge
from crater_app.core.series import keyframe_span, measure_series
from crater_app.core.session import Calibration, Session, load_session_file, save_session_file
from crater_app.core.settings import AnalysisSettings
from crater_app.core.video_reader import VideoReader, iter_frames
from tests.test_analysis_regression import make_side_profile_crater_frame


def true_surface(x):
    """Surface row of make_side_profile_crater_frame at column x."""
    x = np.asarray(x, dtype=np.float64)
    y = 205.0 + 12.0 * (x / 899)
    phase = np.clip((x - 475) / 300, 0, 1)
    inside = (x >= 475) & (x <= 775)
    y = y + np.where(inside, 72.0 * np.sin(np.pi * phase) ** 2, 0.0)
    y -= 7.0 * np.exp(-(((x - 475) / 24.0) ** 2))
    y -= 6.0 * np.exp(-(((x - 775) / 24.0) ** 2))
    return y


def test_snap_recovers_edge_from_an_offset_guide():
    frame = make_side_profile_crater_frame()
    xs = np.arange(320, 880, 1.0)
    offset_guide = [(x, y + 9.0) for x, y in zip(xs, true_surface(xs))]
    refined, support = snap_guide_to_local_edge(frame, offset_guide, AnalysisSettings())
    errors = np.abs(np.array([y for _, y in refined]) - true_surface(xs))
    assert np.median(errors) < 1.5
    assert support > 0.9


def test_snap_reports_no_support_on_a_featureless_region():
    frame = np.full((300, 600, 3), 120, dtype=np.uint8)
    guide = [(float(x), 150.0) for x in range(50, 550)]
    _, support = snap_guide_to_local_edge(frame, guide, AnalysisSettings())
    assert support < 0.1


def test_snap_follows_inverted_polarity():
    frame = 255 - make_side_profile_crater_frame()  # dark above, bright below
    xs = np.arange(320, 880, 1.0)
    guide = [(x, y - 7.0) for x, y in zip(xs, true_surface(xs))]
    refined, _ = snap_guide_to_local_edge(frame, guide, AnalysisSettings())
    errors = np.abs(np.array([y for _, y in refined]) - true_surface(xs))
    assert np.median(errors) < 1.5


def test_guide_for_frame_reports_source_and_distance():
    keys = {100: [(0, 10), (50, 20), (100, 10)], 200: [(0, 30), (50, 40), (100, 30)]}
    mid = guide_for_frame(keys, 150)
    assert mid.source == "interpolated" and mid.frames_to_key == 50
    assert mid.before == 100 and mid.after == 200
    assert abs(np.interp(50, [p[0] for p in mid.points], [p[1] for p in mid.points]) - 30) < 0.6
    assert guide_for_frame(keys, 100).source == "keyframe"
    held = guide_for_frame(keys, 260)
    assert held.source == "held" and held.frames_to_key == 60
    assert held.annotation_confidence < mid.annotation_confidence < 1.0
    assert guide_for_frame({5: [(0, 0), (1, 1)]}, 5) is None  # needs three points


def test_activity_finds_strongest_sustained_burst_not_first_spike():
    frames = np.arange(0, 6000, 10)
    raw = np.full(len(frames), 0.3) + np.random.default_rng(1).normal(0, 0.02, len(frames))
    raw[100] = 12.0  # brief camera bump
    raw[400:430] = np.linspace(9.0, 2.0, 30)  # the experiment: long burst
    scan = analyze_activity(frames, raw)
    assert scan.event_frame == 4000
    assert scan.settled_frame is not None and scan.settled_frame > 4000


def test_session_round_trip_preserves_unknown_keys(tmp_path):
    session = Session(
        "/videos/run.mp4",
        {10: [(1.25, 2.5), (3.0, 4.0), (5.0, 6.0)]},
        Calibration(0.05, "two_point", [(0, 0), (200, 0)], 10.0),
        {"starred_frames": [{"frame_index": 3}]},
    )
    path = tmp_path / "s.json"
    save_session_file(path, session)
    loaded = load_session_file(path)
    assert loaded.keyframes == session.keyframes
    assert loaded.calibration.mm_per_px == 0.05 and loaded.calibration.method == "two_point"
    assert loaded.extra["starred_frames"] == [{"frame_index": 3}]
    assert json.loads(path.read_text())["version"] == 2


def test_legacy_v1_session_loads(tmp_path):
    path = tmp_path / "old.json"
    path.write_text(json.dumps({"video_path": "a.mp4", "starred_frames": [], "guide_keyframes": {"7": [[1, 2], [3, 4], [5, 6]]}}))
    session = load_session_file(path)
    assert session.keyframes == {7: [(1.0, 2.0), (3.0, 4.0), (5.0, 6.0)]}
    assert session.calibration is None


@pytest.fixture()
def synthetic_video(tmp_path):
    path = tmp_path / "run.avi"
    frame = make_side_profile_crater_frame()
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 24.0, (frame.shape[1], frame.shape[0]))
    if not writer.isOpened():
        pytest.skip("no video encoder available")
    for i in range(40):
        marked = frame.copy()
        cv2.putText(marked, str(i), (10, 480), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
        writer.write(marked)
    writer.release()
    return str(path)


def test_reader_sequential_and_backward_access_match_seeks(synthetic_video):
    reader = VideoReader(synthetic_video)
    forward = [reader.get_frame_copy(i) for i in range(10, 20)]
    backward = [reader.get_frame_copy(i) for i in range(19, 9, -1)][::-1]
    for a, b in zip(forward, backward):
        assert np.array_equal(a, b)
    indices = [i for i, _ in iter_frames(synthetic_video, 5, 30, 10, extra=[17])]
    assert indices == [5, 15, 17, 25]


def test_series_and_cli_measure_every_step_plus_keyframes(synthetic_video, tmp_path):
    xs = np.linspace(330, 870, 14)
    line = [(float(x), float(y)) for x, y in zip(xs, true_surface(xs))]
    keys = {3: line, 30: line}
    assert keyframe_span(keys) == (3, 30)
    rows, profiles = measure_series(
        synthetic_video, keys, start=3, stop=30, step=10, fps=24.0, mm_per_px=0.1, include_profiles=True
    )
    assert [r["frame"] for r in rows] == [3, 13, 23, 30]
    assert [r["source"] for r in rows] == ["keyframe", "interpolated", "interpolated", "keyframe"]
    for row in rows:
        assert 25.0 <= row["width_mm"] <= 32.0  # true rim-to-rim ≈ 300 px
        assert 6.5 <= row["depth_mm"] <= 8.0  # true depth ≈ 72 px
    assert profiles and {"frame", "x_mm", "y_mm", "baseline_y_mm"} <= set(profiles[0])

    session_path = tmp_path / "gt_run.json"
    save_session_file(
        session_path, Session(synthetic_video, keys, Calibration.from_frame_width(90.0, 900))
    )
    out = tmp_path / "series.csv"
    assert cli_batch.main(["--session", str(session_path), "--out", str(out), "--frame-step", "10"]) == 0
    with out.open() as handle:
        written = list(csv.DictReader(handle))
    assert [int(r["frame"]) for r in written] == [3, 13, 23, 30]
    assert json.loads(out.with_name("series_meta.json").read_text())["mm_per_px"] == pytest.approx(0.1)
