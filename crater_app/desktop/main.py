"""Crater side-profile analyzer: desktop application."""

from __future__ import annotations

import copy
import csv
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
from PySide6.QtCore import QEvent, QSettings, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from crater_app import __version__
from crater_app.core.activity import ActivityScan, scan_activity
from crater_app.core.analysis import AnalysisEngine
from crater_app.core.guided_profile import GuideSample, densify_guide, guide_for_frame
from crater_app.core.series import (
    SERIES_FIELDS,
    FrameMeasurement,
    keyframe_span,
    measure_frame,
    measure_series,
)
from crater_app.core.session import (
    Calibration,
    Session,
    find_sessions_for_video,
    load_session_file,
    save_session_file,
)
from crater_app.core.video_reader import VideoReader
from crater_app.desktop import theme
from crater_app.desktop.canvas import FrameCanvas, Overlays
from crater_app.desktop.section import SectionView
from crater_app.desktop.sessions import _sanitize_name, default_session_dir
from crater_app.desktop.timeline import Timeline

Point = Tuple[float, float]
WEAK_EDGE = 0.30
DEFAULT_FRAME_WIDTH_MM = 124.0
DOCS_URL = "https://github.com/braydenherzberg/crater_tracker/blob/main/docs/analysis_method.md"


class Worker(QThread):
    """Runs a function in the background, reporting progress in 0..1."""

    progressed = Signal(float)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, *args, **kwargs) -> None:
        super().__init__()
        self._fn, self._args, self._kwargs = fn, args, kwargs
        self.cancel_requested = False

    def run(self) -> None:
        try:
            result = self._fn(
                *self._args,
                progress=self.progressed.emit,
                cancelled=lambda: self.cancel_requested,
                **self._kwargs,
            )
            self.done.emit(result)
        except Exception as exc:  # noqa: BLE001 - surfaced to the user
            self.failed.emit(str(exc))


def resample_points(points: List[Point], count: int) -> List[Point]:
    dense = np.asarray(densify_guide(points, 1))
    xs = np.linspace(dense[0, 0], dense[-1, 0], max(3, count))
    ys = np.interp(xs, dense[:, 0], dense[:, 1])
    return [(round(float(x), 1), round(float(y), 1)) for x, y in zip(xs, ys)]


def section_title(text: str) -> QLabel:
    label = QLabel(text.upper())
    label.setObjectName("sectionTitle")
    return label


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = QSettings("CraterProject", "CraterAnalyzer")
        self.session_dir = default_session_dir()
        self.engine = AnalysisEngine()
        self.video: Optional[VideoReader] = None
        self.video_path: Optional[str] = None
        self.frame_index = 0
        self.keyframes: Dict[int, List[Point]] = {}
        self.draft: Optional[Tuple[int, List[Point]]] = None  # uncommitted line
        self.undo_stack: List[Tuple[Dict[int, List[Point]], Optional[Tuple[int, List[Point]]]]] = []
        self.redo_stack: List[Tuple[Dict[int, List[Point]], Optional[Tuple[int, List[Point]]]]] = []
        self.calibration: Optional[Calibration] = None
        self.session_extra: Dict = {}
        self.session_path: Optional[Path] = None
        self.dirty = False
        self.activity: Optional[ActivityScan] = None
        self.keyframe_widths: Dict[int, float] = {}
        self.measurement: Optional[FrameMeasurement] = None
        self.worker: Optional[Worker] = None
        self.play_timer = QTimer(self)
        self.play_timer.timeout.connect(lambda: self.step(1, wrap=False))
        # Background tracking pass over the keyframe span, re-run after edits.
        self.track_timer = QTimer(self)
        self.track_timer.setSingleShot(True)
        self.track_timer.setInterval(900)
        self.track_timer.timeout.connect(self.run_tracking)
        self.track_worker: Optional[Worker] = None
        self.track_rows: List[Dict] = []

        self._build_ui()
        self._build_menus()
        self.setStyleSheet(theme.STYLESHEET)
        self._update_title()
        self._refresh_all()
        geometry = self.settings.value("geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        else:
            self.resize(1440, 900)

    # ================================================================= layout
    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())
        body = QHBoxLayout()
        body.setSpacing(0)
        body.addWidget(self._build_rail())
        body.addWidget(self._build_center(), 1)
        body.addWidget(self._build_inspector())
        root.addLayout(body, 1)
        root.addWidget(self._build_statusbar())
        self.setCentralWidget(central)

    def _build_header(self) -> QWidget:
        header = QFrame()
        header.setObjectName("header")
        header.setFixedHeight(46)
        row = QHBoxLayout(header)
        row.setContentsMargins(12, 0, 12, 0)
        row.setSpacing(10)
        brand = QLabel("CRATER")
        brand.setObjectName("brand")
        row.addWidget(brand)
        self.open_button = QPushButton("Open video…")
        self.open_button.setToolTip("Open a side-camera video (⌘O / Ctrl+O)")
        self.open_button.clicked.connect(self.choose_video)
        row.addWidget(self.open_button)
        self.meta_label = QLabel("")
        self.meta_label.setObjectName("muted")
        self.meta_label.setFont(theme.mono_font(10))
        row.addWidget(self.meta_label)
        row.addStretch(1)
        self.find_event_button = QPushButton("Find event")
        self.find_event_button.setToolTip(
            "Scan the whole run for the experiment event and jump to where the scene settles"
        )
        self.find_event_button.clicked.connect(self.find_event)
        row.addWidget(self.find_event_button)
        sep = QFrame()
        sep.setFixedSize(1, 22)
        sep.setStyleSheet(f"background: {theme.LINE_STRONG};")
        row.addWidget(sep)
        label = QLabel("Session")
        label.setObjectName("muted")
        row.addWidget(label)
        self.session_name = QLineEdit()
        self.session_name.setFixedWidth(210)
        self.session_name.setFont(theme.mono_font(10))
        self.session_name.setToolTip(
            "Saved to the session library. Names starting with gt_ are used as benchmark ground truth."
        )
        self.session_name.returnPressed.connect(self.save_session)
        row.addWidget(self.session_name)
        self.save_button = QPushButton("Save")
        self.save_button.setObjectName("primary")
        self.save_button.setToolTip("Save session (⌘S / Ctrl+S)")
        self.save_button.clicked.connect(self.save_session)
        row.addWidget(self.save_button)
        return header

    def _tool(self, label: str, key: str, tip: str, checkable: bool = False) -> QToolButton:
        button = QToolButton()
        button.setObjectName("tool")
        button.setText(f"{label}\n{key}")
        button.setToolTip(f"{tip}  ({key})")
        button.setCheckable(checkable)
        button.setFixedSize(58, 46)
        return button

    def _build_rail(self) -> QWidget:
        rail = QFrame()
        rail.setObjectName("rail")
        rail.setFixedWidth(68)
        col = QVBoxLayout(rail)
        col.setContentsMargins(5, 10, 5, 10)
        col.setSpacing(4)
        self.edit_tool = self._tool("Edit", "D", "Edit the crater line on this frame", True)
        self.edit_tool.toggled.connect(self.set_edit_mode)
        self.keep_tool = self._tool("Keep", "S", "Keep this line as a keyframe (locks an interpolated line)")
        self.keep_tool.clicked.connect(self.keep_keyframe)
        self.undo_tool = self._tool("Undo", "⌘Z", "Undo the last line edit")
        self.undo_tool.clicked.connect(self.undo)
        self.clear_tool = self._tool("Clear", "X", "Remove this frame's keyframe")
        self.clear_tool.clicked.connect(self.clear_frame)
        self.snap_tool = self._tool("Snap", "E", "Snap the tracked line to the image edge within 14 px", True)
        self.snap_tool.setChecked(True)
        self.snap_tool.toggled.connect(lambda _: (self._refresh_frame(), self.track_timer.start()))
        self.enhance_tool = self._tool("Contrast", "C", "Enhance low contrast (display only)", True)
        self.enhance_tool.toggled.connect(lambda _: self._refresh_frame())
        self.median_tool = self._tool("Median", "T", "Temporal median of 7 frames: suppresses moving dust", True)
        self.median_tool.toggled.connect(lambda _: self._refresh_frame())
        self.scale_tool = self._tool("Scale", "K", "Calibrate: click two points a known distance apart", True)
        self.scale_tool.toggled.connect(self.set_calibrate_mode)
        self.snapshot_tool = self._tool("Image", "P", "Save the frame with overlays as a full-resolution PNG")
        self.snapshot_tool.clicked.connect(self.save_snapshot)
        for widget in (self.edit_tool, self.keep_tool, self.undo_tool, self.clear_tool):
            col.addWidget(widget)
        col.addSpacing(10)
        for widget in (self.snap_tool, self.enhance_tool, self.median_tool):
            col.addWidget(widget)
        col.addSpacing(10)
        for widget in (self.scale_tool, self.snapshot_tool):
            col.addWidget(widget)
        col.addStretch(1)
        return rail

    def _build_center(self) -> QWidget:
        center = QWidget()
        col = QVBoxLayout(center)
        col.setContentsMargins(10, 8, 10, 8)
        col.setSpacing(6)
        bar = QHBoxLayout()
        self.mode_label = QLabel("")
        self.mode_label.setFont(theme.mono_font(10))
        bar.addWidget(self.mode_label, 1)
        self.show_clicks = QCheckBox("clicks")
        self.show_tracked = QCheckBox("tracked")
        self.show_geometry = QCheckBox("baseline + rims")
        for box in (self.show_clicks, self.show_tracked, self.show_geometry):
            box.setChecked(True)
            box.toggled.connect(self._apply_overlay_visibility)
            bar.addWidget(box)
        col.addLayout(bar)
        self.canvas = FrameCanvas()
        self.canvas.pointsEdited.connect(self.on_points_edited)
        self.canvas.calibrationPicked.connect(self.on_calibration_picked)
        self.canvas.cursorMoved.connect(self.on_cursor_moved)
        col.addWidget(self.canvas, 1)
        self.section = SectionView()
        self.section.setFixedHeight(104)
        col.addWidget(self.section)

        transport = QHBoxLayout()
        transport.setSpacing(4)

        def nav(text: str, tip: str, fn) -> QPushButton:
            button = QPushButton(text)
            button.setToolTip(tip)
            button.setFixedHeight(26)
            button.setFocusPolicy(Qt.NoFocus)
            button.clicked.connect(fn)
            transport.addWidget(button)
            return button

        nav("«", "Back 24 frames (Shift+←)", lambda: self.step(-24))
        nav("‹", "Back 1 frame (←)", lambda: self.step(-1))
        self.play_button = nav("Play", "Play / pause (Space)", self.toggle_play)
        nav("›", "Forward 1 frame (→)", lambda: self.step(1))
        nav("»", "Forward 24 frames (Shift+→)", lambda: self.step(24))
        transport.addSpacing(8)
        goto_label = QLabel("Go to")
        goto_label.setObjectName("muted")
        transport.addWidget(goto_label)
        self.goto = QSpinBox()
        self.goto.setFont(theme.mono_font(10))
        self.goto.setFixedWidth(86)
        self.goto.setKeyboardTracking(False)
        self.goto.setButtonSymbols(QSpinBox.NoButtons)
        self.goto.valueChanged.connect(self.seek)
        transport.addWidget(self.goto)
        self.time_label = QLabel("")
        self.time_label.setFont(theme.mono_font(10))
        transport.addWidget(self.time_label)
        transport.addStretch(1)
        nav("◆ prev  [", "Previous keyframe ([)", lambda: self.jump_keyframe(-1))
        nav("next ◆  ]", "Next keyframe (])", lambda: self.jump_keyframe(1))
        col.addLayout(transport)
        self.timeline = Timeline()
        self.timeline.setFixedHeight(118)
        self.timeline.seekRequested.connect(self.seek)
        col.addWidget(self.timeline)
        return center

    def _build_inspector(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("inspector")
        panel.setFixedWidth(330)
        col = QVBoxLayout(panel)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)

        # ---- measurement
        box = QFrame()
        box.setObjectName("section")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(14, 12, 14, 12)
        head = QHBoxLayout()
        head.addWidget(section_title("Measurement"))
        head.addStretch(1)
        self.source_badge = QLabel("")
        self.source_badge.setObjectName("badge")
        self.source_badge.setFont(theme.mono_font(10))
        head.addWidget(self.source_badge)
        lay.addLayout(head)
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        self.value_labels: Dict[str, Tuple[QLabel, QLabel]] = {}
        for i, (key, title) in enumerate(
            [("width", "Width, rim–rim"), ("depth", "Max depth"), ("area", "Section area"), ("tilt", "Baseline tilt")]
        ):
            cell = QVBoxLayout()
            cell.setSpacing(0)
            name = QLabel(title)
            name.setObjectName("muted")
            name.setStyleSheet("font-size: 11px;")
            value = QLabel("—")
            value.setObjectName("value")
            value.setFont(theme.mono_font(15))
            sub = QLabel("")
            sub.setObjectName("dim")
            sub.setFont(theme.mono_font(9))
            cell.addWidget(name)
            cell.addWidget(value)
            cell.addWidget(sub)
            grid.addLayout(cell, i // 2, i % 2)
            self.value_labels[key] = (value, sub)
        lay.addLayout(grid)
        self.quality_label = QLabel("")
        self.quality_label.setObjectName("dim")
        self.quality_label.setFont(theme.mono_font(9))
        lay.addWidget(self.quality_label)
        self.warning_label = QLabel("")
        self.warning_label.setObjectName("warning")
        self.warning_label.setWordWrap(True)
        lay.addWidget(self.warning_label)
        col.addWidget(box)

        # ---- keyframes
        box = QFrame()
        box.setObjectName("section")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(14, 12, 14, 12)
        head = QHBoxLayout()
        head.addWidget(section_title("Keyframes"))
        head.addStretch(1)
        self.keyframe_count = QLabel("")
        self.keyframe_count.setObjectName("muted")
        self.keyframe_count.setFont(theme.mono_font(9))
        head.addWidget(self.keyframe_count)
        lay.addLayout(head)
        self.keyframe_table = QTableWidget(0, 4)
        self.keyframe_table.setHorizontalHeaderLabels(["frame", "t (s)", "pts", "width mm"])
        self.keyframe_table.verticalHeader().setVisible(False)
        self.keyframe_table.setShowGrid(False)
        self.keyframe_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.keyframe_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.keyframe_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.keyframe_table.setFocusPolicy(Qt.NoFocus)
        self.keyframe_table.setFont(theme.mono_font(10))
        self.keyframe_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.keyframe_table.verticalHeader().setDefaultSectionSize(22)
        self.keyframe_table.setMinimumHeight(150)
        self.keyframe_table.cellClicked.connect(
            lambda row, _col: self.seek(int(self.keyframe_table.item(row, 0).data(Qt.UserRole)))
        )
        lay.addWidget(self.keyframe_table, 1)
        hint = QLabel("D edit · click adds · drag moves · right-click deletes · S keeps an interpolated line")
        hint.setObjectName("dim")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        col.addWidget(box, 1)

        # ---- calibration
        box = QFrame()
        box.setObjectName("section")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.addWidget(section_title("Calibration"))
        row = QHBoxLayout()
        width_label = QLabel("Frame width")
        width_label.setObjectName("muted")
        row.addWidget(width_label)
        self.frame_width_mm = QDoubleSpinBox()
        self.frame_width_mm.setRange(1.0, 100000.0)
        self.frame_width_mm.setDecimals(2)
        self.frame_width_mm.setSuffix(" mm")
        self.frame_width_mm.setFont(theme.mono_font(10))
        self.frame_width_mm.setKeyboardTracking(False)
        self.frame_width_mm.setValue(float(self.settings.value("frame_width_mm", DEFAULT_FRAME_WIDTH_MM)))
        self.frame_width_mm.valueChanged.connect(self.on_frame_width_changed)
        row.addWidget(self.frame_width_mm, 1)
        scale_button = QPushButton("Measure…")
        scale_button.setToolTip("Click two points a known distance apart (K)")
        scale_button.clicked.connect(lambda: self.scale_tool.setChecked(True))
        row.addWidget(scale_button)
        lay.addLayout(row)
        self.calibration_label = QLabel("")
        self.calibration_label.setObjectName("dim")
        self.calibration_label.setFont(theme.mono_font(9))
        self.calibration_label.setWordWrap(True)
        lay.addWidget(self.calibration_label)
        col.addWidget(box)

        # ---- export
        box = QFrame()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(14, 12, 14, 14)
        lay.addWidget(section_title("Export time series"))
        row = QHBoxLayout()
        every = QLabel("Every")
        every.setObjectName("muted")
        row.addWidget(every)
        self.export_step = QSpinBox()
        self.export_step.setRange(1, 10000)
        self.export_step.setValue(10)
        self.export_step.setSuffix(" fr")
        self.export_step.setFont(theme.mono_font(10))
        self.export_step.valueChanged.connect(lambda _: self._refresh_export())
        row.addWidget(self.export_step)
        self.export_profiles = QCheckBox("profiles")
        self.export_profiles.setToolTip("Also write every profile point (x, y, baseline) per frame")
        row.addWidget(self.export_profiles)
        row.addStretch(1)
        lay.addLayout(row)
        self.export_range = QLabel("")
        self.export_range.setObjectName("dim")
        self.export_range.setFont(theme.mono_font(9))
        lay.addWidget(self.export_range)
        self.export_button = QPushButton("Export CSV…")
        self.export_button.setToolTip("Measure every sampled frame between the first and last keyframe (⌘E)")
        self.export_button.clicked.connect(self.export_series)
        lay.addWidget(self.export_button)
        col.addWidget(box)
        return panel

    def _build_statusbar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("statusbar")
        bar.setFixedHeight(24)
        row = QHBoxLayout(bar)
        row.setContentsMargins(12, 0, 12, 0)
        self.cursor_label = QLabel("")
        self.status_label = QLabel("")
        hint = QLabel("←/→ 1 fr · ⇧←/→ 24 · [ ] keyframe · N weak frame · Space play · wheel zoom · F fit · alt-drag pan")
        for label in (self.cursor_label, self.status_label, hint):
            label.setObjectName("muted")
            label.setFont(theme.mono_font(9))
        row.addWidget(self.cursor_label)
        row.addSpacing(16)
        row.addWidget(self.status_label, 1)
        row.addWidget(hint)
        return bar

    def _build_menus(self) -> None:
        menu = self.menuBar()

        def action(parent, text, shortcut, fn, checkable_tool: Optional[QToolButton] = None) -> QAction:
            act = QAction(text, self)
            if shortcut:
                act.setShortcut(QKeySequence(shortcut))
            act.setShortcutContext(Qt.WindowShortcut)
            act.triggered.connect(fn)
            if parent is not None:
                parent.addAction(act)
            else:
                self.addAction(act)
            return act

        file_menu = menu.addMenu("&File")
        action(file_menu, "Open Video…", QKeySequence.Open, self.choose_video)
        action(file_menu, "Open Session…", "Ctrl+Shift+O", self.open_session_dialog)
        action(file_menu, "Save Session", QKeySequence.Save, self.save_session)
        file_menu.addSeparator()
        action(file_menu, "Export Time Series CSV…", "Ctrl+E", self.export_series)
        action(file_menu, "Save Snapshot…", "P", self.save_snapshot)
        file_menu.addSeparator()
        action(
            file_menu,
            "Show Session Folder",
            None,
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.session_dir))),
        )
        edit_menu = menu.addMenu("&Edit")
        action(edit_menu, "Undo Line Edit", QKeySequence.Undo, self.undo)
        action(edit_menu, "Redo Line Edit", QKeySequence.Redo, self.redo)
        edit_menu.addSeparator()
        action(edit_menu, "Edit Line", "D", self.edit_tool.toggle)
        action(edit_menu, "Keep as Keyframe", "S", self.keep_keyframe)
        action(edit_menu, "Clear Frame", "X", self.clear_frame)
        action(edit_menu, "Measure Scale", "K", self.scale_tool.toggle)
        view_menu = menu.addMenu("&View")
        action(view_menu, "Snap to Edge", "E", self.snap_tool.toggle)
        action(view_menu, "Enhance Contrast", "C", self.enhance_tool.toggle)
        action(view_menu, "Temporal Median", "T", self.median_tool.toggle)
        action(view_menu, "Fit Frame", "F", self.canvas.reset_view)
        go_menu = menu.addMenu("&Go")
        action(go_menu, "Next Frame", "Right", lambda: self.step(1))
        action(go_menu, "Previous Frame", "Left", lambda: self.step(-1))
        action(go_menu, "Forward 24 Frames", "Shift+Right", lambda: self.step(24))
        action(go_menu, "Back 24 Frames", "Shift+Left", lambda: self.step(-24))
        action(go_menu, "Next Keyframe", "]", lambda: self.jump_keyframe(1))
        action(go_menu, "Previous Keyframe", "[", lambda: self.jump_keyframe(-1))
        action(go_menu, "Play / Pause", "Space", self.toggle_play)
        action(go_menu, "Next Weak Frame", "N", self.next_weak_frame)
        action(go_menu, "Find Event", None, self.find_event)
        action(None, "Undo (Backspace)", "Backspace", self.undo)
        action(None, "Stop Editing", "Escape", self.escape)
        help_menu = menu.addMenu("&Help")
        action(help_menu, "Measurement Method", None, lambda: QDesktopServices.openUrl(QUrl(DOCS_URL)))
        action(help_menu, f"About Crater {__version__}", None, self.show_about)

    # ================================================================== video
    def choose_video(self) -> None:
        if not self.confirm_discard():
            return
        start = self.settings.value("last_dir", str(Path.home()))
        path, _ = QFileDialog.getOpenFileName(
            self, "Open video", start, "Video (*.mp4 *.mov *.avi *.mkv *.m4v);;All files (*)"
        )
        if path:
            self.settings.setValue("last_dir", str(Path(path).parent))
            self.load_video(path)

    def load_video(self, path: str, session: Optional[Session] = None, session_path: Optional[Path] = None) -> bool:
        try:
            video = VideoReader(path)
        except RuntimeError as exc:
            QMessageBox.critical(self, "Open video", str(exc))
            return False
        self.stop_worker()
        if self.video is not None:
            self.video.release()
        self.video, self.video_path = video, path
        self.keyframes, self.draft = {}, None
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.keyframe_widths.clear()
        self.activity = None
        self.session_extra = {}
        self.session_path = None
        self.calibration = None
        self.frame_index = 0
        self.open_button.setText(Path(path).name)
        self.open_button.setToolTip(path)
        self.meta_label.setText(
            f"{video.width}×{video.height}  ·  {video.fps:.3f} fps  ·  {video.frame_count:,} fr"
        )
        self.goto.blockSignals(True)
        self.goto.setRange(0, video.frame_count - 1)
        self.goto.setValue(0)
        self.goto.blockSignals(False)
        self.timeline.set_video(video.frame_count, video.fps)
        self.export_step.setValue(max(1, int(round(video.fps / 24))))
        self.session_name.setText(_sanitize_name(Path(path).stem))

        if session is None:
            matches = find_sessions_for_video(self.session_dir, path)
            if matches:
                try:
                    session, session_path = load_session_file(matches[0]), matches[0]
                except (OSError, ValueError, KeyError):
                    session = None
        if session is not None:
            self._apply_session(session, session_path)
        self.dirty = False
        self._update_title()
        start = min(self.keyframes) if self.keyframes else 0
        self.seek(start)
        self._refresh_all()
        self.track_rows = []
        self.timeline.set_tracking(None, None, None)
        self.track_timer.start()
        if session_path is not None:
            self.flash(f"Loaded session {session_path.name}: {len(self.keyframes)} keyframe(s)")
        return True

    def _apply_session(self, session: Session, path: Optional[Path]) -> None:
        self.keyframes = {k: list(v) for k, v in session.keyframes.items()}
        self.calibration = session.calibration
        self.session_extra = dict(session.extra)
        activity = self.session_extra.get("activity")
        if activity:
            try:
                self.activity = ActivityScan(
                    np.asarray(activity["frames"]),
                    np.asarray(activity["values"]),
                    activity.get("event_frame"),
                    activity.get("settled_frame"),
                )
            except (KeyError, TypeError):
                self.activity = None
        if self.calibration is not None and self.calibration.method == "frame_width" and self.calibration.known_mm:
            self.frame_width_mm.blockSignals(True)
            self.frame_width_mm.setValue(float(self.calibration.known_mm))
            self.frame_width_mm.blockSignals(False)
        self.session_path = path
        if path is not None:
            self.session_name.setText(path.stem)

    # ============================================================ navigation
    def seek(self, frame: int) -> None:
        if self.video is None:
            return
        frame = int(min(max(0, frame), self.video.frame_count - 1))
        if frame != self.frame_index and self.draft is not None and self.draft[0] != frame:
            self.draft = None  # an uncommitted line belongs to its frame
        self.frame_index = frame
        self.goto.blockSignals(True)
        self.goto.setValue(frame)
        self.goto.blockSignals(False)
        if self.edit_tool.isChecked():
            self._prepare_draft()
        self._refresh_frame()

    def step(self, delta: int, wrap: bool = False) -> None:
        if self.video is None:
            return
        target = self.frame_index + delta
        if target >= self.video.frame_count or target < 0:
            if not wrap:
                self.play_timer.stop()
                self.play_button.setText("Play")
                target = min(max(0, target), self.video.frame_count - 1)
        self.seek(target)

    def toggle_play(self) -> None:
        if self.video is None:
            return
        if self.play_timer.isActive():
            self.play_timer.stop()
            self.play_button.setText("Play")
        else:
            self.play_timer.start(33)
            self.play_button.setText("Pause")

    def jump_keyframe(self, direction: int) -> None:
        keys = sorted(self.keyframes)
        if not keys:
            return
        if direction > 0:
            target = next((k for k in keys if k > self.frame_index), None)
        else:
            target = next((k for k in reversed(keys) if k < self.frame_index), None)
        if target is not None:
            self.seek(target)

    # ================================================================ editing
    def _snapshot(self):
        return copy.deepcopy(self.keyframes), copy.deepcopy(self.draft)

    def _push_undo(self) -> None:
        self.undo_stack.append(self._snapshot())
        del self.undo_stack[:-200]
        self.redo_stack.clear()

    def _mark_dirty(self) -> None:
        self.dirty = True
        self._update_title()

    def undo(self) -> None:
        if not self.undo_stack:
            self.flash("Nothing to undo")
            return
        self.redo_stack.append(self._snapshot())
        self.keyframes, self.draft = self.undo_stack.pop()
        self._after_edit()

    def redo(self) -> None:
        if not self.redo_stack:
            return
        self.undo_stack.append(self._snapshot())
        self.keyframes, self.draft = self.redo_stack.pop()
        self._after_edit()

    def _after_edit(self) -> None:
        self._mark_dirty()
        self.track_timer.start()
        self.keyframe_widths = {k: v for k, v in self.keyframe_widths.items() if k in self.keyframes}
        self.keyframe_widths.pop(self.frame_index, None)
        self._refresh_all()

    def _prepare_draft(self) -> None:
        """Entering edit mode on a frame without a keyframe: seed its line."""

        if self.frame_index in self.keyframes:
            self.draft = None
            return
        if self.draft is not None and self.draft[0] == self.frame_index:
            return
        guide = guide_for_frame(self.keyframes, self.frame_index)
        if guide is None:
            self.draft = (self.frame_index, [])
            return
        nearest = guide.before if guide.before is not None else guide.after
        count = len(self.keyframes.get(nearest, [])) or 12
        self.draft = (self.frame_index, resample_points(guide.points, min(40, max(5, count))))

    def set_edit_mode(self, active: bool) -> None:
        if active and self.video is None:
            self.edit_tool.setChecked(False)
            return
        if active:
            self.scale_tool.setChecked(False)
            if self.play_timer.isActive():
                self.toggle_play()
            self._prepare_draft()
        else:
            self.draft = None
        self.canvas.set_mode("edit" if active else "view")
        self._refresh_frame()

    def on_points_edited(self, points: List[Point]) -> None:
        self._push_undo()
        if len(points) >= 3:
            self.keyframes[self.frame_index] = points
            self.draft = None
        else:
            self.keyframes.pop(self.frame_index, None)
            self.draft = (self.frame_index, points)
        self._after_edit()

    def keep_keyframe(self) -> None:
        """Commit the line shown on this frame as a keyframe."""

        if self.video is None or self.frame_index in self.keyframes:
            return
        if self.draft is not None and self.draft[0] == self.frame_index and len(self.draft[1]) >= 3:
            points = self.draft[1]
        else:
            guide = guide_for_frame(self.keyframes, self.frame_index)
            if guide is None:
                self.flash("Press D and click along the crater line first")
                return
            nearest = guide.before if guide.before is not None else guide.after
            points = resample_points(guide.points, len(self.keyframes.get(nearest, [])) or 12)
        self._push_undo()
        self.keyframes[self.frame_index] = points
        self.draft = None
        self._after_edit()
        self.flash(f"Keyframe kept at frame {self.frame_index:,}")

    def clear_frame(self) -> None:
        if self.frame_index not in self.keyframes and self.draft is None:
            return
        self._push_undo()
        self.keyframes.pop(self.frame_index, None)
        self.draft = (self.frame_index, []) if self.edit_tool.isChecked() else None
        self._after_edit()

    def escape(self) -> None:
        if self.scale_tool.isChecked():
            self.scale_tool.setChecked(False)
        elif self.edit_tool.isChecked():
            self.edit_tool.setChecked(False)

    # ============================================================ calibration
    def mm_per_px(self) -> float:
        if self.calibration is not None:
            return self.calibration.mm_per_px
        width = self.video.width if self.video is not None else 1920
        return self.frame_width_mm.value() / max(1, width)

    def on_frame_width_changed(self, value: float) -> None:
        self.settings.setValue("frame_width_mm", value)
        if self.video is not None:
            self.calibration = Calibration.from_frame_width(value, self.video.width)
            self._mark_dirty()
        self._refresh_frame()

    def set_calibrate_mode(self, active: bool) -> None:
        if active and self.video is None:
            self.scale_tool.setChecked(False)
            return
        if active:
            self.edit_tool.setChecked(False)
            self.flash("Scale: click two points a known distance apart (Esc cancels)")
        self.canvas.set_mode("calibrate" if active else ("edit" if self.edit_tool.isChecked() else "view"))
        self._refresh_mode_label()

    def on_calibration_picked(self, a: Point, b: Point) -> None:
        self.scale_tool.setChecked(False)
        distance_px = float(np.hypot(b[0] - a[0], b[1] - a[1]))
        if distance_px < 5:
            self.flash("Points too close together; try again")
            return
        known, ok = QInputDialog.getDouble(
            self,
            "Measure scale",
            f"Distance between the two points is {distance_px:.1f} px.\nReal distance (mm):",
            10.0,
            0.001,
            100000.0,
            3,
        )
        if not ok:
            return
        self.calibration = Calibration(known / distance_px, "two_point", [a, b], known)
        self._mark_dirty()
        self._refresh_all()
        self.flash(f"Scale set: {self.calibration.mm_per_px:.5f} mm/px")

    # ============================================================== rendering
    def _display_frame(self) -> Optional[np.ndarray]:
        if self.video is None:
            return None
        if self.median_tool.isChecked():
            frames = [
                self.video.get_frame(min(self.video.frame_count - 1, max(0, self.frame_index + o)))
                for o in (-12, -8, -4, 0, 4, 8, 12)
            ]
            frames = [f for f in frames if f is not None]
            if frames:
                return np.median(np.stack(frames), axis=0).astype(np.uint8)
        return self.video.get_frame_copy(self.frame_index)

    def _refresh_all(self) -> None:
        self._refresh_keyframe_table()
        self._refresh_calibration()
        self._refresh_export()
        self.timeline.set_keyframes(self.keyframes.keys())
        if self.activity is not None:
            a = self.activity
            self.timeline.set_activity(a.frames, a.activity, a.event_frame, a.settled_frame)
        self._refresh_frame()

    def _refresh_frame(self) -> None:
        video = self.video
        self.timeline.set_current(self.frame_index)
        if video is None:
            self.canvas.set_frame(None)
            self.section.clear("Open a video, then trace the crater line with D")
            self._show_measurement(None)
            self._refresh_mode_label()
            return
        frame = self._display_frame()
        if frame is None:
            return
        self.time_label.setText(f"{self.frame_index / video.fps:.3f} s")
        analysis_frame = frame
        if self.enhance_tool.isChecked():
            lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
            lab[:, :, 0] = cv2.createCLAHE(2.2, (12, 8)).apply(lab[:, :, 0])
            frame = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
        self.canvas.set_frame(frame)

        keys = dict(self.keyframes)
        draft_points: List[Point] = []
        if self.draft is not None and self.draft[0] == self.frame_index:
            draft_points = self.draft[1]
            if len(draft_points) >= 3:
                keys[self.frame_index] = draft_points
        self.measurement = measure_frame(
            self.engine, analysis_frame, keys, self.frame_index, snap=self.snap_tool.isChecked()
        )
        overlays = Overlays()
        if self.frame_index in self.keyframes:
            overlays.clicks = list(self.keyframes[self.frame_index])
            overlays.clicks_are_keyframe = True
        elif draft_points:
            overlays.clicks = list(draft_points)
        elif self.measurement is not None:
            overlays.guide = densify_guide(self.measurement.guide.points, 4)
        if self.measurement is not None:
            result = self.measurement.result
            overlays.tracked = list(result.profile_points)
            geometry = result.geometry
            if geometry is not None:
                overlays.baseline = geometry.baseline_points
                overlays.left_rim, overlays.right_rim = geometry.left_rim, geometry.right_rim
                overlays.deepest = geometry.center
                ci = geometry.crater_points.index(geometry.center)
                overlays.deepest_baseline_y = geometry.baseline_points[ci][1]
                if self.measurement.guide.source == "keyframe" and self.frame_index in self.keyframes:
                    width = result.metrics.max_crater_width_px * self.mm_per_px()
                    if self.keyframe_widths.get(self.frame_index) != width:
                        self.keyframe_widths[self.frame_index] = width
                        self._refresh_keyframe_table()
        self.canvas.set_overlays(overlays)
        self._apply_overlay_visibility()
        self._show_measurement(self.measurement)
        self._refresh_mode_label()

    def _apply_overlay_visibility(self) -> None:
        self.canvas.show_clicks = self.show_clicks.isChecked()
        self.canvas.show_tracked = self.show_tracked.isChecked()
        self.canvas.show_geometry = self.show_geometry.isChecked()
        self.canvas.update()

    def _show_measurement(self, measurement: Optional[FrameMeasurement]) -> None:
        mm = self.mm_per_px()
        geometry = measurement.result.geometry if measurement else None
        warnings: List[str] = []
        if measurement is None:
            self.source_badge.setText("")
            for value, sub in self.value_labels.values():
                value.setText("—")
                sub.setText("")
            self.quality_label.setText("")
            self.section.clear(
                "No crater line yet. Press D and click along the interface, left to right."
                if self.video is not None
                else "Open a video to begin"
            )
        else:
            guide: GuideSample = measurement.guide
            if guide.source == "keyframe":
                badge = "◆ keyframe" if self.frame_index in self.keyframes else "◇ unsaved line"
            elif guide.source == "interpolated":
                badge = f"interpolated · {guide.frames_to_key:,} fr to ◆"
            else:
                badge = f"held · {guide.frames_to_key:,} fr past ◆"
                warnings.append("No keyframe on the other side of this frame; add one to bound the line.")
            self.source_badge.setText(badge)
            metrics = measurement.result.metrics
            if geometry is None:
                for value, sub in self.value_labels.values():
                    value.setText("—")
                    sub.setText("")
                self.quality_label.setText("")
                self.section.clear("The line has no dip below its level ends: no crater measured")
            else:
                values = {
                    "width": (f"{metrics.max_crater_width_px * mm:.2f} mm", f"{metrics.max_crater_width_px:.1f} px"),
                    "depth": (f"{metrics.max_crater_depth_px * mm:.2f} mm", f"{metrics.max_crater_depth_px:.1f} px"),
                    "area": (f"{metrics.crater_area_px * mm * mm:.2f} mm²", f"{metrics.crater_area_px:,.0f} px²"),
                    "tilt": (
                        f"{metrics.baseline_tilt_degrees:+.2f}°",
                        f"rims {geometry.left_rim[0]:.0f} / {geometry.right_rim[0]:.0f} px",
                    ),
                }
                for key, (main, sub) in values.items():
                    self.value_labels[key][0].setText(main)
                    self.value_labels[key][1].setText(sub)
                support = geometry.profile_confidence
                self.quality_label.setText(
                    f"edge support {support:.0%}  ·  confidence {geometry.geometry_confidence:.0%}"
                    if self.snap_tool.isChecked()
                    else f"snap off: measured from your line  ·  confidence {geometry.geometry_confidence:.0%}"
                )
                if self.snap_tool.isChecked() and support < WEAK_EDGE:
                    warnings.append(f"Weak image edge ({support:.0%}). Check the tracked line by eye.")
                warnings.extend(geometry.notes)
                ci = geometry.crater_points.index(geometry.center)
                self.section.set_data(
                    measurement.result.profile_points,
                    geometry.baseline_points,
                    geometry.left_rim,
                    geometry.right_rim,
                    geometry.center,
                    geometry.baseline_points[ci][1],
                    mm,
                )
        self.warning_label.setText("\n".join(warnings))
        self.warning_label.setVisible(bool(warnings))

    def _refresh_mode_label(self) -> None:
        if self.video is None:
            text, accent = "", False
        elif self.scale_tool.isChecked():
            text, accent = "● SCALE  click two points a known distance apart · Esc cancels", True
        elif self.edit_tool.isChecked():
            count = len(self.keyframes.get(self.frame_index, self.draft[1] if self.draft else []))
            state = "keyframe" if self.frame_index in self.keyframes else "not kept yet (S keeps)"
            text, accent = f"● EDITING  {count} pts · {state} · click adds · drag moves · right-click deletes · Esc done", True
        else:
            text, accent = "D to edit the line on this frame", False
        self.mode_label.setText(text)
        self.mode_label.setStyleSheet(f"color: {theme.ACCENT if accent else theme.MUTED};")

    def _refresh_keyframe_table(self) -> None:
        keys = sorted(self.keyframes)
        fps = self.video.fps if self.video else 30.0
        self.keyframe_table.setRowCount(len(keys))
        for row, k in enumerate(keys):
            width = self.keyframe_widths.get(k)
            cells = [f"◆ {k:,}", f"{k / fps:.3f}", str(len(self.keyframes[k])), f"{width:.2f}" if width else "—"]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setData(Qt.UserRole, k)
                if col >= 2:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.keyframe_table.setItem(row, col, item)
        self.keyframe_count.setText(f"{len(keys)} kept")

    def _refresh_calibration(self) -> None:
        mm = self.mm_per_px()
        if self.calibration is not None and self.calibration.method == "two_point":
            detail = f"two-point: {self.calibration.known_mm:g} mm span"
        else:
            detail = "from frame width"
        self.calibration_label.setText(f"{mm:.5f} mm/px  ·  {detail}")

    def _refresh_export(self) -> None:
        span = keyframe_span(self.keyframes)
        if span is None:
            self.export_range.setText("Needs at least one keyframe")
            self.export_button.setEnabled(False)
        else:
            count = (span[1] - span[0]) // max(1, self.export_step.value()) + 1
            self.export_range.setText(f"frames {span[0]:,}–{span[1]:,}  ·  ~{count:,} rows")
            self.export_button.setEnabled(self.video is not None)

    def on_cursor_moved(self, x: float, y: float) -> None:
        if x < 0:
            self.cursor_label.setText("")
            return
        mm = self.mm_per_px()
        self.cursor_label.setText(f"x {x:7.1f}  y {y:7.1f} px  ·  {x * mm:6.2f}, {y * mm:6.2f} mm")

    def flash(self, text: str) -> None:
        self.status_label.setText(text)
        QTimer.singleShot(6000, lambda: self.status_label.text() == text and self.status_label.setText(""))

    def _update_title(self) -> None:
        name = Path(self.video_path).name if self.video_path else "no video"
        mark = " •" if self.dirty else ""
        self.setWindowTitle(f"Crater {__version__} — {name}{mark}")
        self.save_button.setText("Save •" if self.dirty else "Save")

    # =============================================================== sessions
    def _session(self) -> Session:
        extra = dict(self.session_extra)
        if self.activity is not None:
            a = self.activity
            extra["activity"] = {
                "frames": [int(f) for f in a.frames],
                "values": [round(float(v), 4) for v in a.activity],
                "event_frame": a.event_frame,
                "settled_frame": a.settled_frame,
            }
        calibration = self.calibration
        if calibration is None and self.video is not None:
            calibration = Calibration.from_frame_width(self.frame_width_mm.value(), self.video.width)
        return Session(self.video_path or "", dict(self.keyframes), calibration, extra)

    def save_session(self) -> bool:
        if self.video is None:
            return False
        name = _sanitize_name(self.session_name.text().strip() or Path(self.video_path).stem)
        path = self.session_dir / f"{name}.json"
        if path.exists() and path != self.session_path:
            try:
                other = json.loads(path.read_text(encoding="utf-8")).get("video_path")
            except (OSError, ValueError):
                other = None
            if other and Path(other).name != Path(self.video_path).name:
                reply = QMessageBox.question(
                    self,
                    "Save session",
                    f"'{path.name}' belongs to {Path(other).name}. Replace it?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if reply != QMessageBox.Yes:
                    return False
        save_session_file(path, self._session())
        self.session_path = path
        self.session_name.setText(name)
        self.dirty = False
        self._update_title()
        self.flash(f"Saved {path.name}: {len(self.keyframes)} keyframe(s)")
        return True

    def open_session_dialog(self) -> None:
        if not self.confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Open session", str(self.session_dir), "Session (*.json)")
        if not path:
            return
        try:
            session = load_session_file(Path(path))
        except (OSError, ValueError, KeyError) as exc:
            QMessageBox.critical(self, "Open session", f"Could not read the session:\n{exc}")
            return
        video_path = session.video_path
        if not video_path or not Path(video_path).exists():
            QMessageBox.information(
                self, "Open session", "The session's video was not found. Choose where it is now."
            )
            video_path, _ = QFileDialog.getOpenFileName(
                self, "Locate video", str(Path.home()), "Video (*.mp4 *.mov *.avi *.mkv *.m4v)"
            )
            if not video_path:
                return
            session.video_path = video_path
        self.load_video(video_path, session, Path(path))

    def confirm_discard(self) -> bool:
        if not self.dirty:
            return True
        reply = QMessageBox.question(
            self,
            "Unsaved changes",
            "Save the current session first?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Save,
        )
        if reply == QMessageBox.Save:
            return self.save_session()
        return reply == QMessageBox.Discard

    # ========================================================== background jobs
    def run_tracking(self) -> None:
        """Track every sampled frame between keyframes to show where it is weak."""

        if self.track_worker is not None and self.track_worker.isRunning():
            self.track_worker.cancel_requested = True
            self.track_timer.start()  # try again once it has stopped
            return
        span = keyframe_span(self.keyframes)
        if self.video is None or span is None or span[0] == span[1]:
            self.track_rows = []
            self.timeline.set_tracking(None, None, None)
            return
        step = max(1, (span[1] - span[0]) // 240)
        worker = Worker(
            measure_series,
            self.video_path,
            copy.deepcopy(self.keyframes),
            start=span[0],
            stop=span[1],
            step=step,
            fps=self.video.fps,
            mm_per_px=1.0,
            snap=self.snap_tool.isChecked(),
        )
        worker.progressed.connect(lambda p: self.timeline.set_busy(f"tracking {p:.0%}"))
        worker.done.connect(lambda result, w=worker: self._tracking_done(result, w))
        worker.finished.connect(lambda: self.timeline.set_busy(None))
        self.track_worker = worker
        worker.start()

    def _tracking_done(self, result, worker: Worker) -> None:
        if worker.cancel_requested or worker is not self.track_worker:
            return
        rows, _ = result
        self.track_rows = rows

        def number(value) -> float:
            return float(value) if value not in ("", None) else float("nan")

        self.timeline.set_tracking(
            [r["frame"] for r in rows],
            [number(r["edge_support"]) for r in rows],
            [number(r["width_mm"]) for r in rows],
        )
        weak = sum(1 for r in rows if number(r["edge_support"]) < WEAK_EDGE or r["edge_support"] == "")
        if weak:
            self.flash(f"Tracking weak on {weak} of {len(rows)} sampled frames (amber on the timeline). N jumps to the next.")

    def next_weak_frame(self) -> None:
        weak = [
            r["frame"]
            for r in self.track_rows
            if r["edge_support"] == "" or float(r["edge_support"]) < WEAK_EDGE
        ]
        target = next((f for f in weak if f > self.frame_index), weak[0] if weak else None)
        if target is None:
            self.flash("No weak frames in the tracked range")
        else:
            self.seek(target)

    def stop_worker(self) -> None:
        if self.track_worker is not None and self.track_worker.isRunning():
            self.track_worker.cancel_requested = True
            self.track_worker.wait(5000)
        if self.worker is not None and self.worker.isRunning():
            self.worker.cancel_requested = True
            self.worker.wait(5000)
        self.worker = None
        self.find_event_button.setText("Find event")
        self.timeline.set_busy(None)

    def find_event(self) -> None:
        if self.video is None:
            return
        if self.worker is not None and self.worker.isRunning():
            self.stop_worker()
            return
        if self.activity is not None:
            self._jump_after_event()
            return
        self.worker = Worker(scan_activity, self.video_path, self.video.frame_count)
        self.worker.progressed.connect(
            lambda p: (
                self.find_event_button.setText(f"Scanning {p:.0%} · stop"),
                self.timeline.set_busy(f"scanning run {p:.0%}"),
            )
        )
        self.worker.done.connect(self._event_found)
        self.worker.failed.connect(lambda msg: QMessageBox.warning(self, "Find event", msg))
        self.worker.finished.connect(lambda: (self.find_event_button.setText("Find event"), self.timeline.set_busy(None)))
        self.worker.start()

    def _event_found(self, scan: Optional[ActivityScan]) -> None:
        if scan is None:
            return
        self.activity = scan
        self._mark_dirty()
        self.timeline.set_activity(scan.frames, scan.activity, scan.event_frame, scan.settled_frame)
        if scan.event_frame is None:
            self.flash("No clear event found; the activity trace is on the timeline")
            return
        self._jump_after_event()

    def _jump_after_event(self) -> None:
        scan = self.activity
        if scan is None or scan.event_frame is None or self.video is None:
            return
        target = scan.settled_frame or min(self.video.frame_count - 1, scan.event_frame + int(2 * self.video.fps))
        self.seek(target)
        self.flash(
            f"Event at frame {scan.event_frame:,} ({scan.event_frame / self.video.fps:.2f} s); "
            f"showing {target:,}, where the scene settles"
        )

    def export_series(self) -> None:
        span = keyframe_span(self.keyframes)
        if self.video is None or span is None:
            return
        default = str(Path(self.video_path).with_name(f"{Path(self.video_path).stem}_crater_series.csv"))
        path, _ = QFileDialog.getSaveFileName(self, "Export time series", default, "CSV (*.csv)")
        if not path:
            return
        dialog = QProgressDialog("Measuring frames…", "Cancel", 0, 1000, self)
        dialog.setWindowTitle("Export time series")
        dialog.setWindowModality(Qt.WindowModal)
        dialog.setMinimumDuration(0)
        worker = Worker(
            measure_series,
            self.video_path,
            dict(self.keyframes),
            start=span[0],
            stop=span[1],
            step=self.export_step.value(),
            fps=self.video.fps,
            mm_per_px=self.mm_per_px(),
            snap=self.snap_tool.isChecked(),
            include_profiles=self.export_profiles.isChecked(),
        )
        worker.progressed.connect(lambda p: dialog.setValue(int(p * 1000)))
        dialog.canceled.connect(lambda: setattr(worker, "cancel_requested", True))
        worker.failed.connect(lambda msg: QMessageBox.warning(self, "Export", msg))
        worker.done.connect(lambda result: self._write_series(path, result, worker.cancel_requested))
        worker.finished.connect(dialog.close)
        self._export_worker = worker
        worker.start()

    def _write_series(self, path: str, result, cancelled: bool) -> None:
        rows, profiles = result
        if cancelled:
            self.flash("Export cancelled")
            return
        target = Path(path)
        with target.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=SERIES_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        written = [target.name]
        if profiles:
            profile_path = target.with_name(target.stem + "_profiles.csv")
            with profile_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(profiles[0].keys()))
                writer.writeheader()
                writer.writerows(profiles)
            written.append(profile_path.name)
        # Provenance next to the data: what produced these numbers.
        meta = {
            "app_version": __version__,
            "video": self.video_path,
            "frame_step": self.export_step.value(),
            "snap_to_edge": self.snap_tool.isChecked(),
            "session": self._session().to_payload(),
        }
        meta.pop("activity", None)
        meta["session"].pop("activity", None)
        meta_path = target.with_name(target.stem + "_meta.json")
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        written.append(meta_path.name)
        self.flash(f"Exported {len(rows):,} rows → {', '.join(written)}")

    def save_snapshot(self) -> None:
        image = self.canvas.render_snapshot()
        if image is None or self.video_path is None:
            return
        default = str(Path(self.video_path).with_name(f"{Path(self.video_path).stem}_f{self.frame_index}.png"))
        path, _ = QFileDialog.getSaveFileName(self, "Save snapshot", default, "PNG (*.png)")
        if path:
            image.save(path)
            self.flash(f"Saved {Path(path).name}")

    def show_about(self) -> None:
        QMessageBox.about(
            self,
            "Crater",
            f"Crater side-profile analyzer {__version__}\n\n"
            "Operator-guided crater tracing with sub-pixel edge refinement.\n"
            f"Sessions: {self.session_dir}",
        )

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if not self.confirm_discard():
            event.ignore()
            return
        self.stop_worker()
        export = getattr(self, "_export_worker", None)
        if export is not None and export.isRunning():
            export.cancel_requested = True
            export.wait(10000)
        if self.video is not None:
            self.video.release()
        self.settings.setValue("geometry", self.saveGeometry())
        super().closeEvent(event)


def _smoke_test(window: MainWindow, video: Optional[str]) -> int:
    """Used by CI on the packaged app: build the UI, optionally analyse a video."""

    # Dialogs would block forever with nobody to click them: print instead.
    def report(_parent, title, text, *args, **kwargs):
        print(f"{title}: {text}", file=sys.stderr, flush=True)
        return QMessageBox.Discard

    for name in ("critical", "warning", "information", "question"):
        setattr(QMessageBox, name, staticmethod(report))
    QApplication.processEvents()
    if video:
        if not window.load_video(video):
            print("smoke test failed: could not open the video", file=sys.stderr, flush=True)
            return 1
        window.keyframes = {0: [(0.1 * window.video.width, 0.5 * window.video.height),
                                (0.5 * window.video.width, 0.6 * window.video.height),
                                (0.9 * window.video.width, 0.5 * window.video.height)]}
        window.seek(0)
        if window.measurement is None:
            return 1
    print(f"Crater {__version__} smoke test OK", flush=True)
    window.dirty = False
    return 0


class CraterApplication(QApplication):
    """Routes macOS "Open With" / drag-onto-Dock video files to the window."""

    def __init__(self, argv) -> None:
        super().__init__(argv)
        self.window: Optional[MainWindow] = None
        self.pending_file: Optional[str] = None

    def event(self, event) -> bool:  # type: ignore[override]
        if event.type() == QEvent.FileOpen:
            path = event.file()
            if self.window is None:
                self.pending_file = path
            elif self.window.confirm_discard():
                self.window.load_video(path)
            return True
        return super().event(event)


def run_desktop() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("-psn_")]  # macOS Finder arg
    smoke = "--smoke-test" in args
    args = [a for a in args if a != "--smoke-test"]
    app = QApplication.instance() or CraterApplication(sys.argv)
    app.setApplicationName("Crater")
    icon = Path(__file__).resolve().parent / "assets" / "icon.png"
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))
    window = MainWindow()
    if isinstance(app, CraterApplication):
        app.window = window
        if app.pending_file and not args:
            args = [app.pending_file]
    if smoke:
        return _smoke_test(window, args[0] if args else None)
    window.show()
    # Optional: `crater /path/to/video.mp4` opens that video directly.
    if args and Path(args[0]).is_file():
        window.load_video(args[0])
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run_desktop())
