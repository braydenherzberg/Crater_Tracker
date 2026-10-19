"""App-level regression tests; native OS click-through is a separate release check."""
import copy
import csv
import json
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import cv2
import numpy as np
import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from crater_app.desktop import main
from crater_app.desktop.help import STEPS
from crater_app.desktop.legacy import ThresholdTuner
from crater_app.core.session import Session, load_session_file, save_session_file, find_sessions_for_video
from crater_app.core.series import measure_series

PRACTICE = Path(main.__file__).parent / "assets" / "practice.avi"
POINTS = [(80, 180), (150, 180), (210, 180), (245, 186), (270, 206), (295, 214),
          (320, 220), (345, 214), (370, 206), (395, 186), (430, 180), (490, 180), (560, 180)]

@pytest.fixture
def window(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(main, "QSettings", lambda *a: QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat))
    monkeypatch.setattr(main, "default_session_dir", lambda: tmp_path / "sessions")
    w = main.MainWindow()
    yield w
    w.track_timer.stop()
    w.dirty = False
    w.close()
    app.processEvents()


def test_tutorial_real_actions_calibration_trace_and_reopen(window, tmp_path):
    assert not window.export_button.isEnabled()
    assert not window.edit_tool.isEnabled()
    window.show_tutorial()
    tutorial = window.tutorial
    assert len(STEPS) == 7
    tutorial.run_action()  # actual bundled video, no file dialog
    assert window.video.frame_count == 96
    assert window.calibration is None
    assert window._session().calibration is None
    tutorial.go(1)
    tutorial.run_action()
    window.on_frame_width_changed(64)
    assert window.mm_per_px() == pytest.approx(.1)
    tutorial.go(1)
    tutorial.run_action()
    window.on_points_edited(POINTS)
    assert window.frame_index in window.keyframes
    assert window.measurement.result.geometry is not None
    assert 16 < window.measurement.result.metrics.max_crater_width_px * .1 < 22
    assert 3.5 < window.measurement.result.metrics.max_crater_depth_px * .1 < 4.5
    assert window.export_button.isEnabled()
    for i in range(3, 5):
        tutorial.go(1)
        tutorial.run_action()
    assert window.frame_index == 24
    window.keep_keyframe()
    assert set(window.keyframes) == {0, 24}
    tutorial.go(1)
    tutorial.run_action()  # safely handles tracking pending
    tutorial.go(1)
    tutorial.run_action()  # save real session to isolated test directory
    path = window.session_path
    assert path.exists()
    saved = load_session_file(path)
    assert saved.calibration.mm_per_px == pytest.approx(.1)
    assert set(saved.keyframes) == {0, 24}
    assert window.load_video(str(PRACTICE), saved, path)
    assert set(window.keyframes) == {0, 24}


def test_unconfirmed_scale_is_px_and_cannot_export(window, monkeypatch):
    window.load_practice()
    window.on_points_edited(POINTS)
    assert window.calibration is None
    assert window.value_labels['width'][0].text().endswith('px')
    assert window.section.mm_per_px is None
    assert not window.export_button.isEnabled()
    monkeypatch.setattr(main.QFileDialog, "getSaveFileName", lambda *a: pytest.fail("must not open export without calibration"))
    window.export_series()
    assert "Confirm the scale" in window.status_label.text()
    assert window.save_session()
    assert load_session_file(window.session_path).calibration is None


def test_display_aids_do_not_change_measurement_or_series(window):
    window.load_practice()
    window.on_frame_width_changed(64)
    window.on_points_edited(POINTS)
    expected = window.measurement.result.metrics.to_dict()
    # Deliberately wrong display pixels must have no effect on analysis.
    window._display_frame = lambda: np.zeros((360,640,3), np.uint8)
    window.median_tool.setChecked(True)
    window.enhance_tool.setChecked(True)
    assert window.measurement.result.metrics.to_dict() == expected
    rows, _ = measure_series(str(PRACTICE), window.keyframes, start=0, stop=0, step=1, fps=24, mm_per_px=.1)
    assert rows[0]['width_mm'] == pytest.approx(expected['max_crater_width_px']*.1, abs=.0001)


def test_video_switch_stops_play_and_modes_and_snap_roundtrips(window):
    window.load_practice()
    window.snap_tool.setChecked(False)
    assert window.dirty
    assert window._session().extra['snap_to_edge'] is False
    saved = window._session()
    window.scale_tool.setChecked(True)
    window.toggle_play()
    assert window.play_timer.interval() == 42
    assert window.load_video(str(PRACTICE), saved)
    assert not window.play_timer.isActive()
    assert window.canvas.mode == 'view'
    assert not window.scale_tool.isChecked()
    assert not window.snap_tool.isChecked()


def test_export_writes_profiles_and_frozen_provenance_and_cancel_writes_nothing(window, tmp_path):
    window.load_practice()
    window.on_frame_width_changed(64)
    window.on_points_edited(POINTS)
    result = measure_series(str(PRACTICE), window.keyframes, start=0, stop=0, step=1, fps=24, mm_per_px=.1, include_profiles=True)
    metadata = copy.deepcopy({'session':window._session().to_payload(), 'snap_to_edge':True, 'mm_per_px':.1})
    window.on_frame_width_changed(128)
    out = tmp_path / 'out.csv'
    window._write_series(str(out), result, False, metadata)
    rows = list(csv.DictReader(out.open()))
    assert len(rows) == 1
    assert 3.5 < float(rows[0]['depth_mm']) < 4.5
    assert json.loads((tmp_path/'out_meta.json').read_text())['session']['calibration']['mm_per_px'] == .1
    assert (tmp_path/'out_profiles.csv').exists()
    cancelled = tmp_path/'cancelled.csv'
    window._write_series(str(cancelled), result, True, metadata)
    assert not cancelled.exists()


def test_threshold_tuner_has_real_mask_and_reversible_rotation(window):
    window.load_practice()
    frame = window.video.get_frame_copy(0)
    tuner = ThresholdTuner(frame, window, settings={'surface_boundary':180, 'threshold':94})
    assert len(tuner.points) > 50
    assert tuner.use.isEnabled()
    initial = tuner.points.copy()
    tuner.controls['surface_boundary'].setValue(130)
    assert tuner.points != initial
    tuner.tilt.setValue(2)
    raw = tuner.source_points()
    rot = cv2.getRotationMatrix2D((320,180),2,1)
    projected = np.column_stack([np.array(raw),np.ones(len(raw))]) @ rot.T
    original = np.asarray(tuner.points)
    for p in projected:
        assert np.min(np.linalg.norm(original-p,axis=1)) < 1e-8
    tuner.close()


def test_filename_only_match_does_not_apply_another_videos_session(tmp_path):
    save_session_file(tmp_path/'first.json', Session('/data/first/run.mov', {0:POINTS}))
    assert len(find_sessions_for_video(tmp_path,'/data/second/run.mov')) == 1
    assert find_sessions_for_video(tmp_path,'/data/second/run.mov',exact_only=True) == []


def test_two_point_calibration_and_async_export_public_workflow(window, tmp_path, monkeypatch):
    window.load_practice()
    monkeypatch.setattr(main.QInputDialog, 'getDouble', lambda *a: (10.0, True))
    window.on_calibration_picked((40,80),(140,80))
    assert window.calibration.method == 'two_point'
    assert window.mm_per_px() == pytest.approx(.1)
    window.on_points_edited(POINTS)
    window.seek(2)
    window.keep_keyframe()
    out=tmp_path/'async.csv'
    monkeypatch.setattr(main.QFileDialog, 'getSaveFileName', lambda *a: (str(out), 'CSV (*.csv)'))
    window.export_profiles.setChecked(True)
    window.export_series()
    assert window._export_worker.wait(5000)
    QApplication.processEvents()
    assert out.exists()
    rows=list(csv.DictReader(out.open()))
    assert [int(r['frame']) for r in rows] == [0,1,2]
    meta=json.loads((tmp_path/'async_meta.json').read_text())
    assert meta['analysis_pixels'] == 'original frame'
    assert meta['session']['calibration']['method'] == 'two_point'
    assert (tmp_path/'async_profiles.csv').exists()


def test_invalid_session_and_calibration_are_rejected(tmp_path):
    path = tmp_path/'broken.json'
    path.write_text('[]')
    with pytest.raises(ValueError, match='JSON object'):
        load_session_file(path)
    assert find_sessions_for_video(tmp_path, '/test.mov') == []
    for scale in [0, -1, float('nan'), float('inf')]:
        path.write_text(json.dumps({'video_path':'test.mov','calibration':{'mm_per_px':scale}}))
        with pytest.raises(ValueError, match='finite and positive'):
            load_session_file(path)
