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
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressDialog,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from crater_app.core.analysis import AnalysisEngine, AnalysisResult
from crater_app.core.metrics import compute_geometry_metrics, compute_metrics
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
from crater_app import __version__


@dataclass
class StarredEntry:
    frame_index: int
    settings: AnalysisSettings
    profile_points: List[Tuple[int, int]]
    frame_width_px: int
    crater_points: Optional[List[Tuple[int, int]]] = None
    baseline_points: Optional[List[Tuple[int, int]]] = None
    confidence: float = 0.0


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
        self.setWindowTitle(f"Crater Side-Profile Analyzer {__version__}")

        self.settings_store = QSettings("CraterProject", "CraterDesktop")
        self.engine = AnalysisEngine()
        self.video: Optional[VideoReader] = None
        self.current_video_path: Optional[str] = None
        self.analysis_settings = AnalysisSettings()
        self.current_result: Optional[AnalysisResult] = None
        self.current_frame_index = 0
        self.stabilized_frame_index: Optional[int] = None
        self.stabilized_frame: Optional[np.ndarray] = None
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
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QFrame()
        header.setObjectName("appHeader")
        header_row = QHBoxLayout(header)
        header_row.setContentsMargins(22, 14, 18, 14)
        brand_col = QVBoxLayout()
        brand_col.setSpacing(1)
        brand = QLabel("CRATER")
        brand.setObjectName("brandLabel")
        brand_col.addWidget(brand)
        self.video_name_label = QLabel("No run loaded")
        self.video_name_label.setObjectName("runLabel")
        brand_col.addWidget(self.video_name_label)
        header_row.addLayout(brand_col)
        header_row.addStretch(1)
        open_btn = QPushButton("Open video")
        open_btn.setObjectName("secondaryButton")
        open_btn.clicked.connect(self._choose_video)
        header_row.addWidget(open_btn)
        auto_find_btn = QPushButton("Analyze run")
        auto_find_btn.setObjectName("primaryButton")
        auto_find_btn.setToolTip(
            "Find the experiment event, reject transient low-visibility frames, "
            "and select a stable crater candidate."
        )
        auto_find_btn.clicked.connect(self._auto_find_crater)
        header_row.addWidget(auto_find_btn)
        root.addWidget(header)

        workspace = QWidget()
        workspace_row = QHBoxLayout(workspace)
        workspace_row.setContentsMargins(16, 16, 16, 16)
        workspace_row.setSpacing(16)

        viewer = QFrame()
        viewer.setObjectName("viewer")
        viewer_col = QVBoxLayout(viewer)
        viewer_col.setContentsMargins(0, 0, 0, 0)
        viewer_col.setSpacing(0)

        self.video_label = QLabel(
            "Open a side-camera run to begin.\n\n"
            "Automatic analysis will locate the event and select a stable review frame."
        )
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setMinimumSize(320, 220)
        self.video_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.video_label.setObjectName("videoCanvas")
        viewer_col.addWidget(self.video_label, 1)

        transport = QFrame()
        transport.setObjectName("transport")
        transport_row = QHBoxLayout(transport)
        transport_row.setContentsMargins(14, 10, 14, 10)
        transport_row.setSpacing(8)
        back_btn = QPushButton("−1")
        back_btn.setToolTip("Previous frame")
        back_btn.clicked.connect(lambda: self._step_frame(-1))
        transport_row.addWidget(back_btn)
        self.play_btn = QPushButton("Play")
        self.play_btn.clicked.connect(self._toggle_play)
        transport_row.addWidget(self.play_btn)
        forward_btn = QPushButton("+1")
        forward_btn.setToolTip("Next frame")
        forward_btn.clicked.connect(lambda: self._step_frame(1))
        transport_row.addWidget(forward_btn)
        self.frame_slider = QSlider(Qt.Horizontal)
        self.frame_slider.setMinimum(0)
        self.frame_slider.setMaximum(0)
        self.frame_slider.valueChanged.connect(self._on_frame_changed)
        transport_row.addWidget(self.frame_slider, 1)
        self.frame_position_label = QLabel("Frame —")
        self.frame_position_label.setMinimumWidth(150)
        self.frame_position_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        transport_row.addWidget(self.frame_position_label)
        viewer_col.addWidget(transport)
        workspace_row.addWidget(viewer, 1)

        controls_panel = QWidget()
        controls_panel.setMinimumWidth(360)
        controls_panel.setMaximumWidth(420)
        controls_panel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        controls_col = QVBoxLayout()
        controls_col.setContentsMargins(8, 0, 8, 8)
        controls_col.setSpacing(10)
        controls_panel.setLayout(controls_col)

        controls_scroll = QScrollArea()
        controls_scroll.setObjectName("inspector")
        controls_scroll.setWidgetResizable(True)
        controls_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        controls_scroll.setWidget(controls_panel)
        controls_scroll.setMinimumWidth(390)
        controls_scroll.setMaximumWidth(420)
        controls_scroll.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        workspace_row.addWidget(controls_scroll, 0)
        root.addWidget(workspace, 1)

        inspector_title = QLabel("Review & measure")
        inspector_title.setObjectName("inspectorTitle")
        controls_col.addWidget(inspector_title)
        controls_col.addWidget(self._build_metrics_panel())
        controls_col.addWidget(self._build_analysis_controls())
        controls_col.addWidget(self._build_overlay_controls())
        controls_col.addWidget(self._build_starred_frames_panel())
        controls_col.addWidget(self._build_export_controls())
        controls_col.addWidget(self._build_presets_controls())
        controls_col.addStretch(1)

        self.setCentralWidget(central)
        self._apply_visual_system()

    def _apply_visual_system(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #11161c; color: #dce5ed; font-size: 13px; }
            #appHeader { background: #171e26; border-bottom: 1px solid #26313c; }
            #brandLabel { color: #f4f8fb; font-size: 22px; font-weight: 800; letter-spacing: 4px; }
            #runLabel { color: #8795a3; font-size: 12px; }
            #viewer { background: #090d11; border: 1px solid #26313c; border-radius: 8px; }
            #videoCanvas { background: #090d11; color: #6f7e8c; font-size: 15px; }
            #transport { background: #171e26; border-top: 1px solid #26313c; }
            #inspector { border: 0; background: #11161c; }
            #inspectorTitle { color: #f4f8fb; font-size: 20px; font-weight: 700; padding: 5px 0 2px 2px; }
            QGroupBox { border: 0; border-top: 1px solid #2a3540; margin-top: 14px; padding-top: 12px; font-weight: 700; color: #aebbc7; }
            QGroupBox::title { subcontrol-origin: margin; left: 0; padding: 0 7px 0 0; }
            QPushButton { background: #202a34; border: 1px solid #33414e; border-radius: 5px; padding: 7px 11px; color: #e7edf2; }
            QPushButton:hover { background: #293641; border-color: #4b5d6d; }
            QPushButton:disabled { color: #596673; background: #171d24; border-color: #26303a; }
            #primaryButton { background: #25a7c6; border-color: #25a7c6; color: #071116; font-weight: 800; padding: 9px 16px; }
            #primaryButton:hover { background: #49bdd6; }
            #secondaryButton { padding: 9px 14px; }
            QComboBox, QDoubleSpinBox { background: #171e26; border: 1px solid #33414e; border-radius: 4px; padding: 5px; }
            QListWidget { background: #0e1318; border: 1px solid #2a3540; border-radius: 4px; }
            QScrollBar:vertical { background: #11161c; width: 10px; }
            QScrollBar::handle:vertical { background: #364552; border-radius: 5px; min-height: 28px; }
            QSlider::groove:horizontal { height: 4px; background: #34414c; border-radius: 2px; }
            QSlider::handle:horizontal { background: #25a7c6; width: 14px; margin: -5px 0; border-radius: 7px; }
            QCheckBox { spacing: 8px; }
            """
        )

    def _build_analysis_controls(self) -> QGroupBox:
        group = QGroupBox("Detection")
        form = QFormLayout(group)
        form.setRowWrapPolicy(QFormLayout.DontWrapRows)

        self.auto_surface_check = QCheckBox("Automatic surface tracking")
        self.auto_surface_check.setChecked(self.analysis_settings.auto_surface)
        self.auto_surface_check.setToolTip(
            "Automatically trace the material/air boundary and infer crater rims, "
            "baseline, depth, width, and area."
        )
        self.auto_surface_check.stateChanged.connect(self._sync_settings)

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

        form.addRow(self.auto_surface_check)
        form.addRow(self._form_label("Channel"), self.channel_combo)
        form.addRow(self._form_label("Tilt (-7..+7, 0.25)"), tilt_row)
        form.addRow(self._form_label("Real Width (mm)"), self.real_width_spin)

        self.manual_controls_container = QWidget()
        manual_form = QFormLayout(self.manual_controls_container)
        manual_form.setContentsMargins(0, 8, 0, 0)
        manual_form.setRowWrapPolicy(QFormLayout.DontWrapRows)
        manual_form.addRow(self._form_label("Threshold"), threshold_row)
        manual_form.addRow(self._form_label("Smoothing"), smoothing_row)
        manual_form.addRow(self._form_label("Despeckle"), despeckle_row)
        manual_form.addRow(self._form_label("Crater Left Boundary"), zone_left_row)
        manual_form.addRow(self._form_label("Crater Right Boundary"), zone_right_row)
        manual_form.addRow(self._form_label("Surface Boundary"), surface_row)
        manual_form.addRow(self._form_label("Scan Mode"), self.scan_toggle)
        self.manual_controls_container.setVisible(not self.analysis_settings.auto_surface)
        form.addRow(self.manual_controls_container)
        self._update_scan_mode_label()
        return group

    def _build_overlay_controls(self) -> QGroupBox:
        group = QGroupBox("View")
        layout = QVBoxLayout(group)
        self.show_mask = QCheckBox("Show Mask Panel")
        self.show_mask.setChecked(False)
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
        self.show_enhanced = QCheckBox("Enhance low contrast")
        self.show_enhanced.setChecked(False)
        self.show_enhanced.setToolTip(
            "Apply local contrast enhancement to the review image only. "
            "Measurements continue to use source pixels."
        )
        self.show_enhanced.stateChanged.connect(self._render_current)
        for widget in (
            self.show_mask,
            self.show_guides,
            self.show_profile,
            self.show_enhanced,
        ):
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
        group = QGroupBox("Accepted measurements")
        layout = QVBoxLayout(group)

        btn_row = QHBoxLayout()
        self.star_btn = QPushButton("Accept current")
        self.star_btn.setEnabled(False)
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

        self.starred_count_label = QLabel("0 accepted frames")
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
        group = QGroupBox("Candidate")
        layout = QVBoxLayout(group)
        self.metrics_label = QLabel("No metrics yet.")
        self.metrics_label.setWordWrap(True)
        layout.addWidget(self.metrics_label)
        self.analysis_note_label = QLabel(
            "Open a run, then select Analyze run."
        )
        self.analysis_note_label.setWordWrap(True)
        self.analysis_note_label.setStyleSheet("color: #7f8e9b; font-size: 12px;")
        layout.addWidget(self.analysis_note_label)
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
            self.video_name_label.setText(Path(path).name)
            self.stabilized_frame_index = None
            self.stabilized_frame = None
            self.analysis_note_label.setText(
                "Single-frame preview. Select Analyze run for event-aware review."
            )
            self.run_fps = self.video.fps
            self.fps_label.setText(f"FPS: {self.run_fps:.3f}")
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
        if self.video is not None:
            seconds = value / max(0.001, self.video.fps)
            self.frame_position_label.setText(
                f"Frame {value:,}  ·  {seconds:.2f} s"
            )
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
            auto_surface=self.auto_surface_check.isChecked(),
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
            auto_working_width_px=self.analysis_settings.auto_working_width_px,
            auto_search_top_fraction=self.analysis_settings.auto_search_top_fraction,
            auto_search_bottom_fraction=self.analysis_settings.auto_search_bottom_fraction,
            auto_min_crater_width_fraction=self.analysis_settings.auto_min_crater_width_fraction,
            auto_max_crater_width_fraction=self.analysis_settings.auto_max_crater_width_fraction,
        )
        for widget in (
            self.threshold_slider,
            self.smoothing_slider,
            self.despeckle_slider,
            self.zone_left_slider,
            self.zone_right_slider,
            self.surface_slider,
            self.scan_toggle,
        ):
            widget.setEnabled(not self.analysis_settings.auto_surface)
        self.manual_controls_container.setVisible(
            not self.analysis_settings.auto_surface
        )
        self._render_current()

    def _render_current(self) -> None:
        if self.video is None:
            return
        if (
            self.stabilized_frame_index == self.current_frame_index
            and self.stabilized_frame is not None
        ):
            frame = self.stabilized_frame.copy()
        else:
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

    def _build_temporally_stabilized_frame(
        self, frame_index: int
    ) -> Optional[np.ndarray]:
        if self.video is None:
            return None
        offsets = (-12, -8, -4, 0, 4, 8, 12)
        frames = []
        for offset in offsets:
            index = min(
                self.video.frame_count - 1,
                max(0, frame_index + offset),
            )
            frame = self.video.get_frame_copy(index)
            if frame is not None:
                frames.append(frame)
        if not frames:
            return None
        if len(frames) == 1:
            return frames[0]
        return np.median(np.stack(frames), axis=0).astype(np.uint8)

    def _compose_result(self, result: AnalysisResult, settings: AnalysisSettings) -> np.ndarray:
        current_frame = result.frame.copy()
        if self.show_enhanced.isChecked():
            lab = cv2.cvtColor(current_frame, cv2.COLOR_BGR2LAB)
            lightness, channel_a, channel_b = cv2.split(lab)
            lightness = cv2.createCLAHE(
                clipLimit=2.2, tileGridSize=(12, 8)
            ).apply(lightness)
            current_frame = cv2.cvtColor(
                cv2.merge((lightness, channel_a, channel_b)),
                cv2.COLOR_LAB2BGR,
            )
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
            if not settings.auto_surface:
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
            if result.geometry is not None:
                crater_pts = np.asarray(
                    result.geometry.crater_points, dtype=np.int32
                ).reshape((-1, 1, 2))
                baseline_pts = np.asarray(
                    result.geometry.baseline_points, dtype=np.int32
                ).reshape((-1, 1, 2))
                for panel in (current_frame, mask_display):
                    cv2.polylines(
                        panel, [crater_pts], isClosed=False, color=(0, 165, 255), thickness=4
                    )
                    cv2.polylines(
                        panel, [baseline_pts], isClosed=False, color=(255, 200, 0), thickness=2
                    )
                    cv2.circle(panel, result.geometry.left_rim, 7, (255, 80, 80), -1)
                    cv2.circle(panel, result.geometry.right_rim, 7, (255, 80, 80), -1)
                    cv2.circle(panel, result.geometry.center, 7, (0, 80, 255), -1)

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
        frame_width = max(1, result.frame.shape[1])
        mm_per_px = self.analysis_settings.real_width_mm / frame_width
        width_mm = m.max_crater_width_px * mm_per_px
        depth_mm = m.max_crater_depth_px * mm_per_px
        area_mm2 = m.crater_area_px * (mm_per_px**2)
        self.metrics_label.setText(
            "\n".join(
                [
                    f"{result.status} ({result.detection_mode})",
                    f"Rim-to-rim width: {width_mm:.2f} mm  ({m.max_crater_width_px:.1f} px)",
                    f"Maximum depth: {depth_mm:.2f} mm  ({m.max_crater_depth_px:.1f} px)",
                    f"Cross-section area: {area_mm2:.2f} mm²  ({m.crater_area_px:.1f} px²)",
                    f"Baseline tilt: {m.baseline_tilt_degrees:+.2f}°",
                    f"Confidence: {m.confidence:.0%}",
                    (
                        f"Surface visibility: {result.geometry.profile_confidence:.0%}"
                        if result.geometry is not None
                        else "Surface visibility: unavailable"
                    ),
                ]
            )
        )
        self.star_btn.setEnabled(
            result.detection_mode == "manual"
            or (
                result.geometry is not None
                and result.metrics.confidence >= 0.42
                and result.geometry.profile_confidence >= 0.35
            )
        )
        if self.star_btn.isEnabled():
            self.star_btn.setToolTip(
                "Accept this reviewed frame and geometry for export."
            )
        else:
            self.star_btn.setToolTip(
                "Acceptance is disabled because the automatic evidence is weak. "
                "Try contrast/channel controls or switch to manual mode."
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
            crater_points=(
                list(self.current_result.geometry.crater_points)
                if self.current_result.geometry is not None
                else None
            ),
            baseline_points=(
                list(self.current_result.geometry.baseline_points)
                if self.current_result.geometry is not None
                else None
            ),
            confidence=self.current_result.metrics.confidence,
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
        self.auto_surface_check.blockSignals(True)
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

        self.auto_surface_check.setChecked(settings.auto_surface)
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
        self.auto_surface_check.blockSignals(False)

        self.analysis_settings = copy.deepcopy(settings)
        self._sync_settings()

    def _auto_find_crater(self) -> None:
        if self.video is None or self.video.frame_count <= 0:
            QMessageBox.warning(self, "Auto Find Crater", "Open a video first.")
            return
        if not self.analysis_settings.auto_surface:
            QMessageBox.warning(
                self,
                "Auto Find Crater",
                "Enable Automatic side-profile tracking first.",
            )
            return

        sample_count = min(72, self.video.frame_count)
        indices = np.unique(
            np.linspace(0, self.video.frame_count - 1, sample_count, dtype=int)
        )
        progress = QProgressDialog(
            "Sampling the video for crater candidates…",
            "Cancel",
            0,
            len(indices),
            self,
        )
        progress.setWindowTitle("Auto Find Crater")
        progress.setMinimumDuration(0)
        best_index: Optional[int] = None
        best_status = ""
        candidate_rows = []
        scan_rows = []
        for position, frame_index in enumerate(indices, start=1):
            progress.setValue(position - 1)
            progress.setLabelText(
                f"Analyzing frame {frame_index:,} of {self.video.frame_count - 1:,}"
            )
            QApplication.processEvents()
            if progress.wasCanceled():
                break
            frame = self.video.get_frame_copy(int(frame_index))
            if frame is None:
                continue
            thumb = cv2.cvtColor(
                cv2.resize(frame, (320, 180), interpolation=cv2.INTER_AREA),
                cv2.COLOR_BGR2GRAY,
            )
            thumb = cv2.GaussianBlur(thumb, (7, 7), 0)
            candidate = self.engine.analyze_frame(frame, self.analysis_settings)
            scan_rows.append((int(frame_index), thumb, candidate))
            width = candidate.metrics.max_crater_width_px
            depth = candidate.metrics.max_crater_depth_px
            if (
                width <= 0.0
                or depth / width > 0.65
                or abs(candidate.metrics.baseline_tilt_degrees) > 20.0
            ):
                continue
            score = (
                depth
                * (0.25 + candidate.metrics.confidence)
            )
            candidate_rows.append((score, int(frame_index), candidate, thumb))
        progress.setValue(len(indices))

        event_frame = 0
        reference_thumb = None
        if scan_rows:
            reference_count = max(1, min(5, len(scan_rows) // 10))
            reference_thumb = np.median(
                np.stack([row[1] for row in scan_rows[:reference_count]]),
                axis=0,
            ).astype(np.float32)
            motion_rows = []
            for row_index in range(1, len(scan_rows)):
                previous = scan_rows[row_index - 1][1].astype(np.float32)
                current = scan_rows[row_index][1].astype(np.float32)
                delta = current - previous
                delta -= float(np.median(delta))
                # Favor the material/air region and ignore most overhead hardware.
                score = float(np.mean(np.abs(delta[35:125, 10:310])))
                motion_rows.append((score, row_index))
            if motion_rows:
                motion_values = np.asarray([row[0] for row in motion_rows])
                high_motion = float(np.percentile(motion_values, 90))
                earliest_search = max(1, int(len(scan_rows) * 0.08))
                event_candidates = [
                    row
                    for row in motion_rows
                    if row[1] >= earliest_search and row[0] >= high_motion
                ]
                if event_candidates:
                    # The first major transition is normally the experiment;
                    # later camera handling should not replace it.
                    _, event_position = min(event_candidates, key=lambda row: row[1])
                    event_frame = scan_rows[event_position][0]

        sample_gap = max(1, int(self.video.frame_count / max(1, sample_count)))
        post_event_rows = [
            row
            for row in candidate_rows
            if row[1] >= event_frame + sample_gap
            and row[2].geometry is not None
            and row[2].geometry.profile_confidence >= 0.45
        ]
        rows_to_rank = post_event_rows or candidate_rows

        if rows_to_rank:
            # Require temporal change and favor geometry that persists across
            # neighboring post-event samples. Static pre-run mounds, transient
            # dust edges, and glare should not win on shape alone.
            change_values = []
            if reference_thumb is not None:
                for _, _, _, thumb in rows_to_rank:
                    delta = thumb.astype(np.float32) - reference_thumb
                    delta -= float(np.median(delta))
                    change_values.append(
                        float(np.mean(np.abs(delta[35:125, 10:310])))
                    )
            change_low = float(np.percentile(change_values, 15)) if change_values else 0.0
            change_high = float(np.percentile(change_values, 90)) if change_values else 1.0
            ranked_rows = []
            for row_number, (score, frame_index, candidate, _) in enumerate(rows_to_rank):
                metric = candidate.metrics
                support = 0
                for _, other_index, other, _ in rows_to_rank:
                    if other_index == frame_index:
                        continue
                    if abs(other_index - frame_index) > max(
                        3, int(self.video.frame_count / max(1, sample_count)) * 3
                    ):
                        continue
                    other_metric = other.metrics
                    center_close = abs(
                        other_metric.crater_center_x_px - metric.crater_center_x_px
                    ) <= max(30.0, metric.max_crater_width_px * 0.30)
                    width_close = abs(
                        other_metric.max_crater_width_px - metric.max_crater_width_px
                    ) <= max(40.0, metric.max_crater_width_px * 0.45)
                    if center_close and width_close:
                        support += 1
                stability_multiplier = 0.70 + min(0.60, support * 0.15)
                if change_values:
                    change_signal = float(
                        np.clip(
                            (change_values[row_number] - change_low)
                            / max(0.001, change_high - change_low),
                            0.0,
                            1.0,
                        )
                    )
                else:
                    change_signal = 1.0
                temporal_multiplier = 0.15 + (0.85 * change_signal)
                ranked_rows.append(
                    (
                        score * stability_multiplier * temporal_multiplier,
                        frame_index,
                        candidate,
                    )
                )
            _, best_index, best_candidate = max(ranked_rows, key=lambda row: row[0])
            best_status = f"Post-event · {best_candidate.status}"

        if best_index is None:
            QMessageBox.warning(
                self,
                "Analyze Run",
                "No stable post-event crater candidate was found. "
                "Review the event manually or adjust the view controls.",
            )
            return
        self.stabilized_frame_index = best_index
        self.stabilized_frame = self._build_temporally_stabilized_frame(best_index)
        self.analysis_note_label.setText(
            f"Event-aware selection near frame {event_frame:,}. "
            "Review uses a 7-frame temporal median to suppress moving dust and glare."
        )
        self.frame_slider.setValue(best_index)
        if self.current_frame_index == best_index:
            self._render_current()
        self.statusBar().showMessage(
            f"Selected frame {best_index:,} after event near frame {event_frame:,} — {best_status}",
            10000,
        )

    def _refresh_starred_list(self) -> None:
        self.starred_list.clear()
        for idx in sorted(self.starred_frames.keys()):
            entry = self.starred_frames[idx]
            label = f"Frame {idx}  (thr={entry.settings.threshold}, tilt={entry.settings.tilt_degrees:+.2f})"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, idx)
            self.starred_list.addItem(item)
        count = len(self.starred_frames)
        self.starred_count_label.setText(
            f"{count} accepted frame{'s' if count != 1 else ''}"
        )

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
                    "crater_points": (
                        [[x, y] for x, y in entry.crater_points]
                        if entry.crater_points
                        else []
                    ),
                    "baseline_points": (
                        [[x, y] for x, y in entry.baseline_points]
                        if entry.baseline_points
                        else []
                    ),
                    "confidence": entry.confidence,
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
            crater_points = [
                (int(p[0]), int(p[1])) for p in item.get("crater_points", [])
            ]
            baseline_points = [
                (int(p[0]), int(p[1])) for p in item.get("baseline_points", [])
            ]
            self.starred_frames[frame_idx] = StarredEntry(
                frame_index=frame_idx,
                settings=settings,
                profile_points=profile_points,
                frame_width_px=frame_width_px,
                crater_points=crater_points or None,
                baseline_points=baseline_points or None,
                confidence=float(item.get("confidence", 0.0)),
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
            if entry.crater_points and entry.baseline_points:
                m = compute_geometry_metrics(
                    entry.crater_points,
                    entry.baseline_points,
                    entry.confidence,
                )
            else:
                center_x = entry.frame_width_px // 2
                bracket_left = center_x - entry.settings.zone_left
                bracket_right = center_x + entry.settings.zone_right
                zone_pts = [
                    (x, y)
                    for x, y in entry.profile_points
                    if bracket_left < x < bracket_right
                ]
                crater_pts = self._trim_to_crater(
                    zone_pts, entry.settings.surface_boundary
                )
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
