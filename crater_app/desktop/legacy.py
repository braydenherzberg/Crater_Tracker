"""Original threshold/mask workflow, used to seed a reviewable guide."""
import cv2
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QComboBox, QDoubleSpinBox, QDialog, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSpinBox, QVBoxLayout
from crater_app.core.analysis import AnalysisEngine
from crater_app.core.settings import AnalysisSettings
from crater_app.desktop.canvas import FrameCanvas, Overlays


class ThresholdTuner(QDialog):
    def __init__(self, frame, parent=None, settings=None):
        super().__init__(parent)
        self.frame = frame
        self.initial = settings or {}
        self.engine = AnalysisEngine()
        self.points = []
        self.setWindowTitle("Original threshold tuner · current frame")
        self.resize(1000, 680)
        self.setMinimumSize(740, 540)
        layout = QVBoxLayout(self)
        hint = QLabel("Tune the original threshold and boundary controls. Check the profile against the video before using it as an editable keyframe.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        images = QHBoxLayout()
        self.preview, self.mask = FrameCanvas(), FrameCanvas()
        for title, canvas in (("Video + candidate", self.preview), ("Threshold mask + candidate", self.mask)):
            col = QVBoxLayout()
            col.addWidget(QLabel(title))
            col.addWidget(canvas, 1)
            images.addLayout(col)
        layout.addLayout(images, 1)
        controls = QGridLayout()
        h, w = frame.shape[:2]
        self.controls = {}
        for i, (key, label, lo, hi, value) in enumerate([
            ("threshold", "Threshold", 0, 255, 94),
            ("smoothing", "Smoothing", 1, 100, 15),
            ("despeckle", "Despeckle", 0, 50, 6),
            ("zone_left", "Left bound from center (px)", 0, w // 2, w // 4),
            ("zone_right", "Right bound from center (px)", 0, w // 2, w // 4),
            ("surface_boundary", "Surface boundary Y (px)", 0, h - 1, h // 2),
        ]):
            spin = QSpinBox()
            spin.setRange(lo, hi)
            spin.setValue(self.initial.get(key, value))
            spin.valueChanged.connect(self.refresh)
            controls.addWidget(QLabel(label), i // 3 * 2, i % 3)
            controls.addWidget(spin, i // 3 * 2 + 1, i % 3)
            self.controls[key] = spin
        layout.addLayout(controls)
        self.bottom_up = QCheckBox("Scan bottom-up (off = top-down)")
        self.bottom_up.setChecked(bool(self.initial.get("scan_mode", 1)))
        self.bottom_up.toggled.connect(self.refresh)
        layout.addWidget(self.bottom_up)
        row = QHBoxLayout()
        row.addWidget(QLabel("Channel"))
        self.channel = QComboBox()
        self.channel.addItems(["Grey", "Blue", "Green", "Red"])
        self.channel.setCurrentIndex(int(self.initial.get("channel", 0)))
        self.channel.currentIndexChanged.connect(self.refresh)
        row.addWidget(self.channel)
        row.addWidget(QLabel("Image tilt"))
        self.tilt = QDoubleSpinBox()
        self.tilt.setRange(-7.0, 7.0)
        self.tilt.setSingleStep(0.1)
        self.tilt.setSuffix("°")
        self.tilt.setValue(float(self.initial.get("tilt_degrees", 0)))
        self.tilt.valueChanged.connect(self.refresh)
        row.addWidget(self.tilt)
        layout.addLayout(row)
        self.status = QLabel()
        layout.addWidget(self.status)
        row = QHBoxLayout()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        row.addStretch()
        self.use = QPushButton("Use reviewed profile as keyframe")
        self.use.setObjectName("primary")
        self.use.clicked.connect(self.accept)
        row.addWidget(self.use)
        layout.addLayout(row)
        self.refresh()

    def analysis_settings(self):
        h, w = self.frame.shape[:2]
        return AnalysisSettings(auto_surface=False, **{k: s.value() for k, s in self.controls.items()},
                                scan_mode=int(self.bottom_up.isChecked()), channel=self.channel.currentIndex(), tilt_degrees=self.tilt.value(),
                                left_margin=min(100, w // 10), right_margin=min(100, w // 10),
                                top_margin=min(50, h // 10))

    def refresh(self):
        result = self.engine.analyze_frame(self.frame, self.analysis_settings())
        self.points = list(result.profile_points)
        self.preview.set_frame(result.frame)
        self.mask.set_frame(cv2.cvtColor(result.solid_mask, cv2.COLOR_GRAY2BGR))
        settings = self.analysis_settings()
        w = self.frame.shape[1]
        overlay = Overlays(tracked=self.points, baseline=[(0, settings.surface_boundary), (w-1, settings.surface_boundary)],
                           left_rim=(w//2-settings.zone_left, settings.surface_boundary),
                           right_rim=(w//2+settings.zone_right, settings.surface_boundary))
        self.preview.set_overlays(overlay)
        self.mask.set_overlays(overlay)
        self.use.setEnabled(len(self.points) >= 3)
        self.status.setText(f"{len(self.points)} candidate points · Dashed line = surface boundary; ticks = zone bounds. Verify the physical interface.")

    def source_points(self):
        """Undo the preview rotation before storing a guide on the raw frame."""
        import numpy as np
        h, w = self.frame.shape[:2]
        inverse = cv2.invertAffineTransform(cv2.getRotationMatrix2D((w // 2, h // 2), self.tilt.value(), 1.0))
        points = np.asarray(self.points, dtype=float)
        raw = np.column_stack([points, np.ones(len(points))]) @ inverse.T
        return sorted((float(x), float(y)) for x, y in raw if 0 <= x < w and 0 <= y < h)
