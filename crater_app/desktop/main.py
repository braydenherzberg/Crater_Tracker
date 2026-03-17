from __future__ import annotations

import copy
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from crater_app.core.analysis import AnalysisEngine, AnalysisResult
from crater_app.core.metrics import compute_metrics
from crater_app.core.settings import AnalysisSettings
from crater_app.core.video_reader import VideoReader
from crater_app.desktop.exporter import export_metrics_csv, export_profile_csv, export_snapshot
from crater_app.desktop.presets import (
    default_preset_dir,
    delete_named_preset,
    list_presets,
    load_preset,
    rename_named_preset,
    save_named_preset,
    save_preset,
)
from crater_app.desktop.sessions import (
    default_session_dir,
    delete_named_session,
    list_sessions,
    load_session,
    rename_named_session,
    save_named_session,
    save_session,
)


@dataclass
class StarredEntry:
    frame_index: int
    settings: AnalysisSettings
    profile_points: List[Tuple[int, int]]
    frame_width_px: int


def frame_to_pixmap(frame_bgr: np.ndarray) -> QPixmap:
    rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    h, w, _ = rgb.shape
    image = QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888)
    return QPixmap.fromImage(image)


class CraterDashboardWindow(QMainWindow):
    LABEL_TOOLTIPS: Dict[str, str] = {
        "Threshold": "Binary threshold used to separate crater/solid pixels from background.",
        "Smoothing": "Moving-average smoothing strength for the green profile trace.",
        "Despeckle": "Median filter window used before smoothing to suppress outliers.",
        "Channel": "Image channel used for detection (Grayscale, Blue, Green, Red).",
        "Crater Left Boundary": "Left offset from frame center defining crater search zone.",
        "Crater Right Boundary": "Right offset from frame center defining crater search zone.",
        "Surface Boundary": "Reference baseline used for depth/area calculations.",
        "Scan Mode": "Bottom-Up or Top-Down scan mode for locating profile edge.",
        "Tilt (-7..+7, 0.25)": "Frame rotation before analysis in 0.25 degree increments.",
        "Real Width (mm)": "Real-world width of full frame used for mm calibration.",
        "Guide Left": "Left margin of the blue guide rectangle in pixels.",
        "Guide Right": "Right margin of the blue guide rectangle in pixels.",
        "Guide Top": "Top margin of the blue guide rectangle in pixels.",
    }

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Crater Analysis Desktop")

        self.settings_store = QSettings("CraterProject", "CraterDesktop")
        self.engine = AnalysisEngine()
        self.video: Optional[VideoReader] = None
        self.current_video_path: Optional[str] = None
        self.analysis_settings = AnalysisSettings()
        self.current_result: Optional[AnalysisResult] = None
        self.current_frame_index = 0
        self.starred_frames: Dict[int, StarredEntry] = {}
        self.run_fps: float = 30.0

        self.preset_dir = default_preset_dir()
        self.preset_dir.mkdir(parents=True, exist_ok=True)
        self.session_dir = default_session_dir()
        self.session_dir.mkdir(parents=True, exist_ok=True)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._advance_frame)

        self._build_ui()
        self._restore_window_state()

    def closeEvent(self, event):  # type: ignore[override]
        if self.video is not None:
            self.video.release()
        self._persist_window_state()
        super().closeEvent(event)

    def resizeEvent(self, event):  # type: ignore[override]
        super().resizeEvent(event)
        self._render_current()

    def _build_ui(self) -> None:
        central = QWidget()
        root = QHBoxLayout(central)

        self.video_label = QLabel(
            "Open a video to begin.\n\nPlease preprocess video first: crop and cut to length."
        )
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setMinimumSize(320, 220)
        self.video_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        root.addWidget(self.video_label, 1)

        controls_panel = QWidget()
        controls_panel.setMinimumWidth(280)
        controls_panel.setMaximumWidth(420)
        controls_panel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        controls_col = QVBoxLayout()
        controls_panel.setLayout(controls_col)

        controls_scroll = QScrollArea()
        controls_scroll.setWidgetResizable(True)
        controls_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        controls_scroll.setWidget(controls_panel)
        controls_scroll.setMinimumWidth(340)
        controls_scroll.setMaximumWidth(340)
        controls_scroll.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        root.addWidget(controls_scroll, 0)

        file_group = QGroupBox("File")
        file_form = QVBoxLayout(file_group)
        file_form.setSpacing(4)
        file_form.setContentsMargins(6, 6, 6, 4)
        open_btn = QPushButton("Open Video")
        open_btn.clicked.connect(self._choose_video)
        file_form.addWidget(open_btn)

        play_row = QHBoxLayout()
        self.play_btn = QPushButton("Play")
        self.play_btn.clicked.connect(self._toggle_play)
        play_row.addWidget(self.play_btn)
        back_btn = QPushButton("< Back")
        back_btn.clicked.connect(lambda: self._step_frame(-1))
        play_row.addWidget(back_btn)
        forward_btn = QPushButton("Next >")
        forward_btn.clicked.connect(lambda: self._step_frame(1))
        play_row.addWidget(forward_btn)
        file_form.addLayout(play_row)

        self.frame_slider = QSlider(Qt.Horizontal)
        self.frame_slider.setMinimum(0)
        self.frame_slider.setMaximum(0)
        self.frame_slider.valueChanged.connect(self._on_frame_changed)
        self.frame_slider.hide()
        file_form.addWidget(self.frame_slider)
        controls_col.addWidget(file_group)
        controls_col.setSpacing(4)

        controls_col.addWidget(self._build_analysis_controls())
        controls_col.addWidget(self._build_starred_frames_panel())
        controls_col.addWidget(self._build_presets_controls())
        controls_col.addWidget(self._build_export_controls())
        controls_col.addWidget(self._build_overlay_controls())
        controls_col.addWidget(self._build_metrics_panel())
        controls_col.addStretch(1)

        self.setCentralWidget(central)

    def _build_analysis_controls(self) -> QGroupBox:
        group = QGroupBox("Analysis Controls")
        form = QFormLayout(group)
        form.setRowWrapPolicy(QFormLayout.DontWrapRows)

        self.threshold_slider, self.threshold_label, threshold_row = self._slider_control(
            0, 255, self.analysis_settings.threshold
        )
        self.smoothing_slider, self.smoothing_label, smoothing_row = self._slider_control(
            1, 100, self.analysis_settings.smoothing
        )
        self.despeckle_slider, self.despeckle_label, despeckle_row = self._slider_control(
            0, 51, self.analysis_settings.despeckle
        )
        self.zone_left_slider, self.zone_left_label, zone_left_row = self._slider_control(
            0, 4000, self.analysis_settings.zone_left
        )
        self.zone_right_slider, self.zone_right_label, zone_right_row = self._slider_control(
            0, 4000, self.analysis_settings.zone_right
        )
        self.surface_slider, self.surface_label, surface_row = self._slider_control(
            0, 4000, self.analysis_settings.surface_boundary
        )
        self.tilt_slider, self.tilt_label, tilt_row = self._slider_control(0, 56, 28)

        self.channel_combo = QComboBox()
        self.channel_combo.addItems(["Grayscale", "Blue", "Green", "Red"])
        self.channel_combo.setCurrentIndex(self.analysis_settings.channel)
        self.channel_combo.currentIndexChanged.connect(lambda _: self._sync_settings())
        self.channel_combo.setToolTip("Choose image channel: Grayscale, Blue, Green, or Red.")

        self.scan_toggle = QPushButton()
        self.scan_toggle.setCheckable(True)
        self.scan_toggle.setChecked(self.analysis_settings.scan_mode == 1)
        self.scan_toggle.clicked.connect(self._sync_settings)
        self.scan_toggle.setToolTip("Toggle between Bottom-Up and Top-Down scan modes.")

        self.real_width_spin = QDoubleSpinBox()
        self.real_width_spin.setRange(0.1, 10000.0)
        self.real_width_spin.setDecimals(1)
        self.real_width_spin.setSingleStep(1.0)
        self.real_width_spin.setValue(self.analysis_settings.real_width_mm)
        self.real_width_spin.setSuffix(" mm")
        self.real_width_spin.setToolTip("Physical width of the full camera view in mm (for calibration).")
        self.real_width_spin.valueChanged.connect(lambda _: self._sync_settings())

        self.threshold_slider.setToolTip("Threshold")
        self.smoothing_slider.setToolTip("Smoothing")
        self.despeckle_slider.setToolTip("Despeckle")
        self.zone_left_slider.setToolTip("Crater Left Boundary")
        self.zone_right_slider.setToolTip("Crater Right Boundary")
        self.surface_slider.setToolTip("Surface Boundary")
        self.tilt_slider.setToolTip("Tilt angle (-7 to +7 in 0.25 degree steps)")

        form.addRow(self._form_label("Threshold"), threshold_row)
        form.addRow(self._form_label("Smoothing"), smoothing_row)
        form.addRow(self._form_label("Despeckle"), despeckle_row)
        form.addRow(self._form_label("Channel"), self.channel_combo)
        form.addRow(self._form_label("Crater Left Boundary"), zone_left_row)
        form.addRow(self._form_label("Crater Right Boundary"), zone_right_row)
        form.addRow(self._form_label("Surface Boundary"), surface_row)
        form.addRow(self._form_label("Scan Mode"), self.scan_toggle)
        form.addRow(self._form_label("Tilt (-7..+7, 0.25)"), tilt_row)
        form.addRow(self._form_label("Real Width (mm)"), self.real_width_spin)
        self._update_scan_mode_label()
        return group

    def _build_overlay_controls(self) -> QGroupBox:
        group = QGroupBox("Overlay")
        layout = QVBoxLayout(group)
        self.show_mask = QCheckBox("Show Mask Panel")
        self.show_mask.setChecked(True)
        self.show_mask.setToolTip("Show/hide the lower binary mask preview panel.")
        self.show_mask.stateChanged.connect(self._render_current)
        self.show_guides = QCheckBox("Show Guides")
        self.show_guides.setChecked(True)
        self.show_guides.setToolTip("Show/hide guide overlays (blue box, yellow bounds, surface line).")
        self.show_guides.stateChanged.connect(self._render_current)
        self.show_profile = QCheckBox("Show Profile")
        self.show_profile.setChecked(True)
        self.show_profile.setToolTip("Show/hide the green traced crater profile.")
        self.show_profile.stateChanged.connect(self._render_current)
        for widget in (self.show_mask, self.show_guides, self.show_profile):
            layout.addWidget(widget)

        self.guide_left_slider, self.guide_left_label, guide_left_row = self._slider_control(
            0, 4000, self.analysis_settings.left_margin
        )
        self.guide_right_slider, self.guide_right_label, guide_right_row = self._slider_control(
            0, 4000, self.analysis_settings.right_margin
        )
        self.guide_top_slider, self.guide_top_label, guide_top_row = self._slider_control(
            0, 4000, self.analysis_settings.top_margin
        )
        self.guide_left_slider.setToolTip("Left guide margin in pixels for the blue rectangle.")
        self.guide_right_slider.setToolTip("Right guide margin in pixels for the blue rectangle.")
        self.guide_top_slider.setToolTip("Top guide margin in pixels for the blue rectangle.")
        guide_form = QFormLayout()
        guide_form.setRowWrapPolicy(QFormLayout.DontWrapRows)
        guide_form.addRow(self._form_label("Guide Left"), guide_left_row)
        guide_form.addRow(self._form_label("Guide Right"), guide_right_row)
        guide_form.addRow(self._form_label("Guide Top"), guide_top_row)
        layout.addLayout(guide_form)
        return group

    def _build_starred_frames_panel(self) -> QGroupBox:
        group = QGroupBox("Starred Frames")
        layout = QVBoxLayout(group)

        btn_row = QHBoxLayout()
        self.star_btn = QPushButton("Star Frame")
        self.star_btn.setToolTip("Bookmark this frame with current settings/profile for export.")
        self.star_btn.clicked.connect(self._star_current_frame)
        btn_row.addWidget(self.star_btn)
        self.unstar_btn = QPushButton("Remove")
        self.unstar_btn.setToolTip("Remove the selected starred frame.")
        self.unstar_btn.clicked.connect(self._remove_starred_frame)
        btn_row.addWidget(self.unstar_btn)
        layout.addLayout(btn_row)

        self.session_combo = QComboBox()
        self.session_combo.setToolTip("Saved sessions stored in ~/.crater_analysis/sessions")
        layout.addWidget(self.session_combo)

        session_row1 = QHBoxLayout()
        session_row2 = QHBoxLayout()
        save_selected_session_btn = QPushButton("Save")
        save_selected_session_btn.setToolTip("Overwrite selected session with current starred frames/settings.")
        save_selected_session_btn.clicked.connect(self._save_selected_session)
        save_session_btn = QPushButton("Save As")
        save_session_btn.setToolTip("Save current starred session under a new name.")
        save_session_btn.clicked.connect(self._save_session_to_library)
        load_session_btn = QPushButton("Load")
        load_session_btn.setToolTip("Load selected session from the session library.")
        load_session_btn.clicked.connect(self._load_selected_session)
        rename_session_btn = QPushButton("Rename")
        rename_session_btn.setToolTip("Rename selected session.")
        rename_session_btn.clicked.connect(self._rename_selected_session)
        delete_session_btn = QPushButton("Delete")
        delete_session_btn.setToolTip("Delete selected session.")
        delete_session_btn.clicked.connect(self._delete_selected_session)
        refresh_sessions_btn = QPushButton("Refresh")
        refresh_sessions_btn.setToolTip("Refresh session list from disk.")
        refresh_sessions_btn.clicked.connect(self._refresh_sessions_list)
        session_row1.addWidget(save_selected_session_btn)
        session_row1.addWidget(save_session_btn)
        session_row1.addWidget(load_session_btn)
        session_row2.addWidget(rename_session_btn)
        session_row2.addWidget(delete_session_btn)
        session_row2.addWidget(refresh_sessions_btn)
        layout.addLayout(session_row1)
        layout.addLayout(session_row2)

        self.starred_list = QListWidget()
        self.starred_list.setMaximumHeight(120)
        self.starred_list.itemClicked.connect(self._jump_to_starred_frame)
        self.starred_list.setToolTip("Click a frame to jump to it and load its saved settings.")
        layout.addWidget(self.starred_list)

        self.starred_count_label = QLabel("0 frames starred")
        layout.addWidget(self.starred_count_label)
        self._refresh_sessions_list()
        return group

    def _build_presets_controls(self) -> QGroupBox:
        group = QGroupBox("Control Presets")
        layout = QVBoxLayout(group)
        self.preset_combo = QComboBox()
        self.preset_combo.setToolTip("Presets stored in ~/.crater_analysis/presets")
        layout.addWidget(self.preset_combo)

        row1 = QHBoxLayout()
        row2 = QHBoxLayout()
        save_selected_btn = QPushButton("Save")
        save_selected_btn.setToolTip("Overwrite selected preset with current controls.")
        save_selected_btn.clicked.connect(self._save_selected_preset)
        save_btn = QPushButton("Save As")
        save_btn.setToolTip("Save controls as a new preset.")
        save_btn.clicked.connect(self._save_preset_to_library)
        load_btn = QPushButton("Load")
        load_btn.setToolTip("Load selected preset into controls.")
        load_btn.clicked.connect(self._load_selected_preset)
        delete_btn = QPushButton("Delete")
        delete_btn.setToolTip("Delete selected preset.")
        delete_btn.clicked.connect(self._delete_selected_preset)
        rename_btn = QPushButton("Rename")
        rename_btn.setToolTip("Rename selected preset.")
        rename_btn.clicked.connect(self._rename_selected_preset)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.setToolTip("Refresh preset list from disk.")
        refresh_btn.clicked.connect(self._refresh_presets_list)
        row1.addWidget(save_selected_btn)
        row1.addWidget(save_btn)
        row1.addWidget(load_btn)
        row2.addWidget(rename_btn)
        row2.addWidget(delete_btn)
        row2.addWidget(refresh_btn)
        layout.addLayout(row1)
        layout.addLayout(row2)
        self._refresh_presets_list()
        return group

    def _build_export_controls(self) -> QGroupBox:
        group = QGroupBox("Export")
        layout = QVBoxLayout(group)
        row1 = QHBoxLayout()
        row2 = QHBoxLayout()
        snap_btn = QPushButton("Snapshot")
        snap_btn.setToolTip("Save current rendered frame as a PNG image.")
        snap_btn.clicked.connect(self._export_snapshot)
        profile_btn = QPushButton("Starred Profiles CSV")
        profile_btn.setToolTip("Export calibrated (frame, x_mm, y_mm) rows for starred frames.")
        profile_btn.clicked.connect(self._export_starred_profiles)
        metrics_btn = QPushButton("Starred Metrics CSV")
        metrics_btn.setToolTip("Export calibrated crater metrics (mm/mm^2) for each starred frame.")
        metrics_btn.clicked.connect(self._export_starred_metrics)
        fps_btn = QPushButton("Set FPS")
        fps_btn.setToolTip("Set run FPS used to compute timestamp_ms in exported CSV files.")
        fps_btn.clicked.connect(self._set_run_fps)
        self.fps_label = QLabel(f"FPS: {self.run_fps:.2f}")
        self.fps_label.setToolTip("Current FPS used for timestamp conversion. frame 1 (index 0) = 0 ms.")
        row1.addWidget(snap_btn)
        row1.addWidget(profile_btn)
        row2.addWidget(metrics_btn)
        row2.addWidget(fps_btn)
        row2.addWidget(self.fps_label)
        layout.addLayout(row1)
        layout.addLayout(row2)
        return group

    def _build_metrics_panel(self) -> QGroupBox:
        group = QGroupBox("Metrics")
        layout = QVBoxLayout(group)
        self.metrics_label = QLabel("No metrics yet.")
        self.metrics_label.setWordWrap(True)
        layout.addWidget(self.metrics_label)
        return group

    def _slider_control(self, lo: int, hi: int, value: int) -> tuple[QSlider, QLabel, QWidget]:
        slider = QSlider(Qt.Horizontal)
        slider.setRange(lo, hi)
        slider.setValue(value)
        slider.setMinimumWidth(150)
        label = QLabel(str(value))
        label.setMinimumWidth(44)
        label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(slider, 1)
        layout.addWidget(label)
        slider.valueChanged.connect(lambda _: self._sync_settings())
        return slider, label, row

    def _form_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setToolTip(self.LABEL_TOOLTIPS.get(text, text))
        return label

    def _update_scan_mode_label(self) -> None:
        self.scan_toggle.setText("Bottom-Up" if self.scan_toggle.isChecked() else "Top-Down")

    def _choose_video(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Video",
            "",
            "Video Files (*.mp4 *.mov *.avi *.mkv);;All Files (*)",
        )
        if not path:
            return
        self._load_video_path(path)

    def _load_video_path(self, path: str) -> None:
        try:
            if self.video is not None:
                self.video.release()
            self.video = VideoReader(path)
            self.current_video_path = path
            self.current_frame_index = 0
            self.frame_slider.setMaximum(max(0, self.video.frame_count - 1))
            self.frame_slider.setValue(0)
            self.frame_slider.show()
            first_frame = self.video.get_frame(0)
            if first_frame is not None:
                h, w = first_frame.shape[:2]
                half_w = max(1, w // 2)
                self.zone_left_slider.setMaximum(half_w)
                self.zone_right_slider.setMaximum(half_w)
                self.surface_slider.setMaximum(max(1, h - 1))
                self.guide_left_slider.setMaximum(max(1, w - 1))
                self.guide_right_slider.setMaximum(max(1, w - 1))
                self.guide_top_slider.setMaximum(max(1, h - 1))
            self._render_current()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Video Error", str(exc))

    def _toggle_play(self) -> None:
        if self.video is None:
            return
        if self.timer.isActive():
            self.timer.stop()
            self.play_btn.setText("Play")
        else:
            self.timer.start(33)
            self.play_btn.setText("Pause")

    def _advance_frame(self) -> None:
        self._step_frame(1)

    def _step_frame(self, delta: int) -> None:
        if self.video is None:
            return
        nxt = (self.current_frame_index + delta) % self.video.frame_count
        self.frame_slider.blockSignals(True)
        self.frame_slider.setValue(nxt)
        self.frame_slider.blockSignals(False)
        self._on_frame_changed(nxt)

    def _on_frame_changed(self, value: int) -> None:
        self.current_frame_index = value
        self._render_current()

    def _sync_settings(self) -> None:
        tilt = (self.tilt_slider.value() - 28) * 0.25
        self.tilt_label.setText(f"{tilt:+.2f} deg")
        self.threshold_label.setText(str(self.threshold_slider.value()))
        self.smoothing_label.setText(str(self.smoothing_slider.value()))
        self.despeckle_label.setText(str(self.despeckle_slider.value()))
        self.zone_left_label.setText(str(self.zone_left_slider.value()))
        self.zone_right_label.setText(str(self.zone_right_slider.value()))
        self.surface_label.setText(str(self.surface_slider.value()))
        self.guide_left_label.setText(str(self.guide_left_slider.value()))
        self.guide_right_label.setText(str(self.guide_right_slider.value()))
        self.guide_top_label.setText(str(self.guide_top_slider.value()))
        self._update_scan_mode_label()
        self.analysis_settings = AnalysisSettings(
            threshold=self.threshold_slider.value(),
            smoothing=self.smoothing_slider.value(),
            despeckle=self.despeckle_slider.value(),
            tilt_degrees=tilt,
            channel=self.channel_combo.currentIndex(),
            zone_left=self.zone_left_slider.value(),
            zone_right=self.zone_right_slider.value(),
            surface_boundary=self.surface_slider.value(),
            scan_mode=1 if self.scan_toggle.isChecked() else 0,
            left_margin=self.guide_left_slider.value(),
            right_margin=self.guide_right_slider.value(),
            top_margin=self.guide_top_slider.value(),
            x_step=self.analysis_settings.x_step,
            real_width_mm=self.real_width_spin.value(),
        )
        self._render_current()

    def _render_current(self) -> None:
        if self.video is None:
            return
        frame = self.video.get_frame_copy(self.current_frame_index)
        if frame is None:
            actual_max = max(0, self.video.frame_count - 1)
            if self.current_frame_index > actual_max:
                self.current_frame_index = actual_max
                self.frame_slider.blockSignals(True)
                self.frame_slider.setMaximum(actual_max)
                self.frame_slider.setValue(actual_max)
                self.frame_slider.blockSignals(False)
                self._render_current()
            return
        settings = self.analysis_settings.normalized(frame.shape[0])
        self.current_result = self.engine.analyze_frame(frame, settings)
        composed = self._compose_result(self.current_result, settings)
        self.video_label.setPixmap(
            frame_to_pixmap(composed).scaled(
                self.video_label.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
        )
        self._update_metrics(self.current_result)

    def _compose_result(self, result: AnalysisResult, settings: AnalysisSettings) -> np.ndarray:
        current_frame = result.frame.copy()
        mask_display = cv2.cvtColor(result.solid_mask, cv2.COLOR_GRAY2BGR)
        h, w, _ = current_frame.shape
        center_x = w // 2
        left = center_x - settings.zone_left
        right = center_x + settings.zone_right

        def draw_both(p1, p2, color, thickness=1):
            cv2.line(current_frame, p1, p2, color, thickness)
            cv2.line(mask_display, p1, p2, color, thickness)

        if self.show_guides.isChecked():
            cv2.rectangle(
                current_frame,
                (settings.left_margin, settings.top_margin),
                (w - settings.right_margin, h),
                (255, 0, 0),
                1,
            )
            draw_both((left, 0), (left, h), (0, 255, 255), 1)
            draw_both((right, 0), (right, h), (0, 255, 255), 1)
            draw_both(
                (settings.left_margin, settings.surface_boundary),
                (w - settings.right_margin, settings.surface_boundary),
                (255, 255, 0),
                2,
            )

        if self.show_profile.isChecked() and len(result.profile_points) > 1:
            pts = np.array(result.profile_points, np.int32).reshape((-1, 1, 2))
            cv2.polylines(current_frame, [pts], isClosed=False, color=(0, 255, 0), thickness=3)
            cv2.polylines(mask_display, [pts], isClosed=False, color=(0, 255, 0), thickness=3)

        cv2.putText(
            current_frame,
            f"Frame {self.current_frame_index}",
            (10, 24),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (255, 255, 255),
            2,
        )
        cv2.putText(
            current_frame,
            f"Tilt {settings.tilt_degrees:+.2f} deg",
            (10, 52),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (200, 255, 255),
            2,
        )

        if self.show_mask.isChecked():
            return np.vstack((current_frame, mask_display))
        return current_frame

    def _update_metrics(self, result: AnalysisResult) -> None:
        m = result.metrics
        self.metrics_label.setText(
            "\n".join(
                [
                    f"points: {m.point_count}",
                    f"avg_crater_width_px: {m.avg_crater_width_px:.1f}",
                    f"max_crater_width_px: {m.max_crater_width_px:.1f}",
                    f"trace_width_px: {m.trace_width_px:.1f}",
                    f"max_crater_depth_px: {m.max_crater_depth_px:.1f}",
                    f"crater_area_px: {m.crater_area_px:.1f}",
                    f"confidence: {m.confidence:.2f}",
                ]
            )
        )

    def _star_current_frame(self) -> None:
        if self.video is None or self.current_result is None:
            QMessageBox.warning(self, "Star Frame", "Open a video and navigate to a frame first.")
            return
        frame = self.video.get_frame(self.current_frame_index)
        if frame is None:
            return
        frame_w = frame.shape[1]
        entry = StarredEntry(
            frame_index=self.current_frame_index,
            settings=copy.deepcopy(self.analysis_settings),
            profile_points=list(self.current_result.profile_points),
            frame_width_px=frame_w,
        )
        self.starred_frames[self.current_frame_index] = entry
        self._refresh_starred_list()

    def _remove_starred_frame(self) -> None:
        item = self.starred_list.currentItem()
        if item is None:
            QMessageBox.warning(self, "Remove", "Select a starred frame first.")
            return
        frame_idx = item.data(Qt.UserRole)
        if frame_idx in self.starred_frames:
            del self.starred_frames[frame_idx]
        self._refresh_starred_list()

    def _jump_to_starred_frame(self, item: QListWidgetItem) -> None:
        frame_idx = item.data(Qt.UserRole)
        if frame_idx is None or self.video is None:
            return
        entry = self.starred_frames.get(frame_idx)
        if entry is not None:
            self._apply_settings_to_ui(entry.settings)
        self.frame_slider.blockSignals(True)
        self.frame_slider.setValue(frame_idx)
        self.frame_slider.blockSignals(False)
        self._on_frame_changed(frame_idx)

    def _apply_settings_to_ui(self, settings: AnalysisSettings) -> None:
        self.threshold_slider.blockSignals(True)
        self.smoothing_slider.blockSignals(True)
        self.despeckle_slider.blockSignals(True)
        self.zone_left_slider.blockSignals(True)
        self.zone_right_slider.blockSignals(True)
        self.surface_slider.blockSignals(True)
        self.tilt_slider.blockSignals(True)
        self.channel_combo.blockSignals(True)
        self.scan_toggle.blockSignals(True)
        self.real_width_spin.blockSignals(True)
        self.guide_left_slider.blockSignals(True)
        self.guide_right_slider.blockSignals(True)
        self.guide_top_slider.blockSignals(True)

        self.threshold_slider.setValue(settings.threshold)
        self.smoothing_slider.setValue(settings.smoothing)
        self.despeckle_slider.setValue(settings.despeckle)
        self.channel_combo.setCurrentIndex(settings.channel)
        self.zone_left_slider.setValue(settings.zone_left)
        self.zone_right_slider.setValue(settings.zone_right)
        self.surface_slider.setValue(settings.surface_boundary)
        self.scan_toggle.setChecked(settings.scan_mode == 1)
        self.tilt_slider.setValue(int(round((settings.tilt_degrees / 0.25) + 28)))
        self.real_width_spin.setValue(settings.real_width_mm)
        self.guide_left_slider.setValue(settings.left_margin)
        self.guide_right_slider.setValue(settings.right_margin)
        self.guide_top_slider.setValue(settings.top_margin)

        self.threshold_slider.blockSignals(False)
        self.smoothing_slider.blockSignals(False)
        self.despeckle_slider.blockSignals(False)
        self.zone_left_slider.blockSignals(False)
        self.zone_right_slider.blockSignals(False)
        self.surface_slider.blockSignals(False)
        self.tilt_slider.blockSignals(False)
        self.channel_combo.blockSignals(False)
        self.scan_toggle.blockSignals(False)
        self.real_width_spin.blockSignals(False)
        self.guide_left_slider.blockSignals(False)
        self.guide_right_slider.blockSignals(False)
        self.guide_top_slider.blockSignals(False)

        self.analysis_settings = copy.deepcopy(settings)
        self._sync_settings()

    def _refresh_starred_list(self) -> None:
        self.starred_list.clear()
        for idx in sorted(self.starred_frames.keys()):
            entry = self.starred_frames[idx]
            label = f"Frame {idx}  (thr={entry.settings.threshold}, tilt={entry.settings.tilt_degrees:+.2f})"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, idx)
            self.starred_list.addItem(item)
        count = len(self.starred_frames)
        self.starred_count_label.setText(f"{count} frame{'s' if count != 1 else ''} starred")

    def _refresh_presets_list(self) -> None:
        names = [p.name for p in list_presets(self.preset_dir)]
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        self.preset_combo.addItems(names)
        self.preset_combo.blockSignals(False)

    def _save_preset_to_library(self) -> None:
        suggested = f"preset_frame_{self.current_frame_index}"
        name, ok = QInputDialog.getText(self, "Save Preset", "Preset name:", text=suggested)
        if not ok:
            return
        name = name.strip()
        if not name:
            QMessageBox.warning(self, "Preset", "Preset name cannot be empty.")
            return
        path = save_named_preset(name, self.analysis_settings, self.preset_dir)
        self._refresh_presets_list()
        idx = self.preset_combo.findText(path.name)
        if idx >= 0:
            self.preset_combo.setCurrentIndex(idx)

    def _save_selected_preset(self) -> None:
        filename = self.preset_combo.currentText()
        if not filename:
            QMessageBox.warning(self, "Preset", "No preset selected.")
            return
        save_preset(str(self.preset_dir / filename), self.analysis_settings)
        QMessageBox.information(self, "Preset Saved", f"Updated preset '{filename}'.")

    def _load_selected_preset(self) -> None:
        filename = self.preset_combo.currentText()
        if not filename:
            QMessageBox.warning(self, "Preset", "No preset selected.")
            return
        preset = load_preset(str(self.preset_dir / filename))
        if preset is None:
            QMessageBox.warning(self, "Preset", "Could not load preset.")
            return
        self._apply_settings_to_ui(preset)
        self._render_current()

    def _rename_selected_preset(self) -> None:
        filename = self.preset_combo.currentText()
        if not filename:
            QMessageBox.warning(self, "Preset", "No preset selected.")
            return
        suggested = Path(filename).stem
        new_name, ok = QInputDialog.getText(self, "Rename Preset", "New preset name:", text=suggested)
        if not ok:
            return
        new_name = new_name.strip()
        if not new_name:
            QMessageBox.warning(self, "Preset", "Preset name cannot be empty.")
            return
        renamed_path = rename_named_preset(filename, new_name, self.preset_dir)
        if renamed_path is None:
            QMessageBox.warning(self, "Preset", "Could not rename selected preset.")
            return
        self._refresh_presets_list()
        idx = self.preset_combo.findText(renamed_path.name)
        if idx >= 0:
            self.preset_combo.setCurrentIndex(idx)

    def _delete_selected_preset(self) -> None:
        filename = self.preset_combo.currentText()
        if not filename:
            QMessageBox.warning(self, "Preset", "No preset selected.")
            return
        reply = QMessageBox.question(
            self,
            "Delete Preset",
            f"Delete preset '{filename}'?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        if not delete_named_preset(filename, self.preset_dir):
            QMessageBox.warning(self, "Preset", "Could not delete selected preset.")
            return
        self._refresh_presets_list()

    def _refresh_sessions_list(self) -> None:
        names = [p.name for p in list_sessions(self.session_dir)]
        self.session_combo.blockSignals(True)
        self.session_combo.clear()
        self.session_combo.addItems(names)
        self.session_combo.blockSignals(False)

    def _build_starred_session_payload(self) -> Dict:
        entries = []
        for frame_idx in sorted(self.starred_frames.keys()):
            entry = self.starred_frames[frame_idx]
            entries.append(
                {
                    "frame_index": entry.frame_index,
                    "settings": entry.settings.to_dict(),
                    "profile_points": [[x, y] for x, y in entry.profile_points],
                    "frame_width_px": entry.frame_width_px,
                }
            )
        return {"video_path": self.current_video_path, "starred_frames": entries}

    def _save_session_to_library(self) -> None:
        if not self.starred_frames:
            QMessageBox.warning(self, "Save Session", "No starred frames to save.")
            return
        suggested = f"session_frame_{self.current_frame_index}"
        name, ok = QInputDialog.getText(self, "Save Session", "Session name:", text=suggested)
        if not ok:
            return
        name = name.strip()
        if not name:
            QMessageBox.warning(self, "Save Session", "Session name cannot be empty.")
            return
        payload = self._build_starred_session_payload()
        path = save_named_session(name, payload, self.session_dir)
        self._refresh_sessions_list()
        idx = self.session_combo.findText(path.name)
        if idx >= 0:
            self.session_combo.setCurrentIndex(idx)
        QMessageBox.information(
            self,
            "Session Saved",
            f"Saved {len(self.starred_frames)} starred frame(s) to session library.",
        )

    def _save_selected_session(self) -> None:
        filename = self.session_combo.currentText()
        if not filename:
            QMessageBox.warning(self, "Save Session", "No session selected.")
            return
        if not self.starred_frames:
            QMessageBox.warning(self, "Save Session", "No starred frames to save.")
            return
        save_session(str(self.session_dir / filename), self._build_starred_session_payload())
        QMessageBox.information(self, "Session Saved", f"Updated session '{filename}'.")

    def _load_selected_session(self) -> None:
        filename = self.session_combo.currentText()
        if not filename:
            QMessageBox.warning(self, "Load Session", "No session selected.")
            return
        try:
            data = load_session(str(self.session_dir / filename))
            if data is None:
                QMessageBox.warning(self, "Load Session", "Could not load selected session.")
                return
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Load Session", f"Failed to read session file:\n{exc}")
            return

        entries = data.get("starred_frames", [])
        if not entries:
            QMessageBox.warning(self, "Load Session", "Session file contains no starred frames.")
            return

        self.starred_frames.clear()
        for item in entries:
            frame_idx = int(item["frame_index"])
            settings = AnalysisSettings.from_dict(item.get("settings", {}))
            profile_points = [(int(p[0]), int(p[1])) for p in item.get("profile_points", [])]
            frame_width_px = int(item.get("frame_width_px", 0))
            self.starred_frames[frame_idx] = StarredEntry(
                frame_index=frame_idx,
                settings=settings,
                profile_points=profile_points,
                frame_width_px=frame_width_px,
            )
        self._refresh_starred_list()

        saved_video_path = data.get("video_path")
        if self.video is None and saved_video_path and Path(saved_video_path).exists():
            reply = QMessageBox.question(
                self,
                "Open Video",
                f"Session references video:\n{saved_video_path}\n\nOpen it now?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if reply == QMessageBox.Yes:
                self._load_video_path(saved_video_path)

        QMessageBox.information(
            self,
            "Session Loaded",
            f"Loaded {len(self.starred_frames)} starred frame(s).",
        )

    def _rename_selected_session(self) -> None:
        filename = self.session_combo.currentText()
        if not filename:
            QMessageBox.warning(self, "Rename Session", "No session selected.")
            return
        suggested = Path(filename).stem
        new_name, ok = QInputDialog.getText(self, "Rename Session", "New session name:", text=suggested)
        if not ok:
            return
        new_name = new_name.strip()
        if not new_name:
            QMessageBox.warning(self, "Rename Session", "Session name cannot be empty.")
            return
        renamed_path = rename_named_session(filename, new_name, self.session_dir)
        if renamed_path is None:
            QMessageBox.warning(self, "Rename Session", "Could not rename selected session.")
            return
        self._refresh_sessions_list()
        idx = self.session_combo.findText(renamed_path.name)
        if idx >= 0:
            self.session_combo.setCurrentIndex(idx)

    def _delete_selected_session(self) -> None:
        filename = self.session_combo.currentText()
        if not filename:
            QMessageBox.warning(self, "Delete Session", "No session selected.")
            return
        reply = QMessageBox.question(
            self,
            "Delete Session",
            f"Delete session '{filename}'?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        if not delete_named_session(filename, self.session_dir):
            QMessageBox.warning(self, "Delete Session", "Could not delete selected session.")
            return
        self._refresh_sessions_list()

    def _export_snapshot(self) -> None:
        if self.current_result is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export Snapshot", "snapshot.png", "PNG (*.png)")
        if not path:
            return
        rendered = self._compose_result(
            self.current_result,
            self.analysis_settings.normalized(self.current_result.frame.shape[0]),
        )
        export_snapshot(rendered, path)

    def _set_run_fps(self) -> None:
        fps, ok = QInputDialog.getDouble(
            self,
            "Set Run FPS",
            "Frames per second:",
            self.run_fps,
            0.01,
            10000.0,
            4,
        )
        if not ok:
            return
        self.run_fps = fps
        self.fps_label.setText(f"FPS: {self.run_fps:.2f}")

    def _frame_timestamp_ms(self, frame_idx: int) -> float:
        if self.run_fps <= 0:
            return 0.0
        return (frame_idx / self.run_fps) * 1000.0

    @staticmethod
    def _trim_to_crater(pts: List[Tuple[int, int]], surface_boundary: int) -> List[Tuple[int, int]]:
        """Keep only the crater portion of the profile, trimming flat wings at surface level.

        Returns the contiguous span where the trace is below the surface,
        plus one rim point on each side so the profile cleanly meets y=0.
        """
        sorted_pts = sorted(pts, key=lambda p: p[0])
        below = [i for i, (_, y) in enumerate(sorted_pts) if y > surface_boundary]
        if not below:
            return []
        lo = max(0, below[0] - 1)
        hi = min(len(sorted_pts) - 1, below[-1] + 1)
        return sorted_pts[lo: hi + 1]

    def _export_starred_profiles(self) -> None:
        if not self.starred_frames:
            QMessageBox.warning(self, "Export", "No starred frames. Star some frames first.")
            return

        sign_choice, ok = QInputDialog.getItem(
            self,
            "Depth Sign Convention",
            "Choose Y-axis direction for depth values:",
            ["Positive-Down (depth values are positive)", "Negative-Down (depth values are negative)"],
            0,
            False,
        )
        if not ok:
            return
        sign = 1.0 if "Positive" in sign_choice else -1.0

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Starred Profiles CSV",
            "starred_profiles.csv",
            "CSV (*.csv)",
        )
        if not path:
            return

        rows = []
        for frame_idx in sorted(self.starred_frames.keys()):
            entry = self.starred_frames[frame_idx]
            if entry.frame_width_px <= 0:
                continue
            mm_per_px = entry.settings.real_width_mm / entry.frame_width_px
            all_pts = sorted(entry.profile_points, key=lambda p: p[0])
            for x_px, y_px in all_pts:
                x_mm = x_px * mm_per_px
                y_mm = (y_px - entry.settings.surface_boundary) * mm_per_px * sign
                rows.append(
                    {
                        "frame": frame_idx,
                        "timestamp_ms": round(self._frame_timestamp_ms(frame_idx), 4),
                        "x_mm": round(x_mm, 4),
                        "y_mm": round(y_mm, 4),
                    }
                )

        export_profile_csv(rows, path)
        QMessageBox.information(
            self,
            "Export Complete",
            f"Exported {len(rows)} profile points from {len(self.starred_frames)} starred frame(s).",
        )

    def _export_starred_metrics(self) -> None:
        if not self.starred_frames:
            QMessageBox.warning(self, "Export", "No starred frames. Star some frames first.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Starred Metrics CSV",
            "starred_metrics.csv",
            "CSV (*.csv)",
        )
        if not path:
            return

        rows = []
        for frame_idx in sorted(self.starred_frames.keys()):
            entry = self.starred_frames[frame_idx]
            if entry.frame_width_px <= 0:
                continue
            mm_per_px = entry.settings.real_width_mm / entry.frame_width_px
            center_x = entry.frame_width_px // 2
            bracket_left = center_x - entry.settings.zone_left
            bracket_right = center_x + entry.settings.zone_right
            zone_pts = [
                (x, y) for x, y in entry.profile_points
                if bracket_left < x < bracket_right
            ]
            crater_pts = self._trim_to_crater(zone_pts, entry.settings.surface_boundary)
            if not crater_pts:
                continue
            m = compute_metrics(crater_pts, entry.settings.surface_boundary)
            rows.append(
                {
                    "frame": frame_idx,
                    "timestamp_ms": round(self._frame_timestamp_ms(frame_idx), 4),
                    "point_count": m.point_count,
                    "avg_crater_width_mm": round(m.avg_crater_width_px * mm_per_px, 4),
                    "max_crater_width_mm": round(m.max_crater_width_px * mm_per_px, 4),
                    "trace_width_mm": round(m.trace_width_px * mm_per_px, 4),
                    "max_crater_depth_mm": round(m.max_crater_depth_px * mm_per_px, 4),
                    "crater_area_mm2": round(m.crater_area_px * (mm_per_px**2), 4),
                    "confidence": round(m.confidence, 4),
                }
            )
        export_metrics_csv(rows, path)
        QMessageBox.information(self, "Export Complete", f"Exported metrics for {len(rows)} starred frame(s).")

    def _persist_window_state(self) -> None:
        self.settings_store.setValue("geometry", self.saveGeometry())
        self.settings_store.setValue("windowState", self.saveState())

    def _restore_window_state(self) -> None:
        geometry = self.settings_store.value("geometry")
        state = self.settings_store.value("windowState")
        if geometry is not None:
            self.restoreGeometry(geometry)
        if state is not None:
            self.restoreState(state)
        if geometry is None:
            self.resize(1280, 820)


def run_desktop() -> int:
    app = QApplication(sys.argv)
    window = CraterDashboardWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run_desktop())

