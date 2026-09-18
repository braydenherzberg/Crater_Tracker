"""Section view: the tracked profile with vertical exaggeration and dimensions."""

from __future__ import annotations

from typing import List, Optional, Tuple

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from . import theme

Point = Tuple[float, float]


class SectionView(QWidget):
    """Draws the crater cross-section so millimetre-scale depth is visible."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(96)
        self.setMouseTracking(True)
        self.profile: List[Point] = []
        self.baseline: List[Point] = []
        self.left_rim: Optional[Point] = None
        self.right_rim: Optional[Point] = None
        self.deepest: Optional[Point] = None
        self.deepest_baseline_y: Optional[float] = None
        self.mm_per_px = 1.0
        self.message = "No crater measurement on this frame"
        self._hover_x: Optional[float] = None

    def set_data(self, profile, baseline, left_rim, right_rim, deepest, deepest_baseline_y, mm_per_px) -> None:
        self.profile = list(profile or [])
        self.baseline = list(baseline or [])
        self.left_rim, self.right_rim = left_rim, right_rim
        self.deepest, self.deepest_baseline_y = deepest, deepest_baseline_y
        self.mm_per_px = mm_per_px
        self.update()

    def clear(self, message: str) -> None:
        self.message = message
        self.set_data([], [], None, None, None, None, self.mm_per_px)

    def _mapping(self):
        xs = np.asarray([p[0] for p in self.profile])
        ys = np.asarray([p[1] for p in self.profile] + [p[1] for p in self.baseline])
        x0, x1 = float(xs.min()), float(xs.max())
        y0, y1 = float(ys.min()), float(ys.max())
        pad_top, pad_bottom, pad_x = 24.0, 10.0, 8.0
        w = max(1.0, self.width() - 2 * pad_x)
        h = max(1.0, self.height() - pad_top - pad_bottom)
        sx = w / max(1.0, x1 - x0)
        sy = h / max(1.0, y1 - y0)
        sy = max(sx, sy)  # never compress depth below true scale

        def to_screen(x: float, y: float) -> QPointF:
            return QPointF(pad_x + (x - x0) * sx, pad_top + (y - y0) * sy)

        return to_screen, sx, sy, x0

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.fillRect(self.rect(), theme.color(theme.PANEL))
        painter.setFont(theme.mono_font(9))
        if len(self.profile) < 2:
            painter.setPen(theme.color(theme.DIM))
            painter.drawText(self.rect(), Qt.AlignCenter, self.message)
            return
        painter.setRenderHint(QPainter.Antialiasing, True)
        to_screen, sx, sy, x0 = self._mapping()
        mm = self.mm_per_px

        if self.baseline:
            painter.setPen(QPen(theme.color(theme.MUTED), 1, Qt.DashLine))
            painter.drawLine(to_screen(*self.baseline[0]), to_screen(*self.baseline[-1]))
        path = QPainterPath()
        for i, (x, y) in enumerate(self.profile):
            p = to_screen(x, y)
            path.moveTo(p) if i == 0 else path.lineTo(p)
        painter.setPen(QPen(theme.color(theme.TEXT), 1.6))
        painter.drawPath(path)

        painter.setPen(QPen(theme.color(theme.MUTED), 1))
        if self.left_rim and self.right_rim:
            a, b = to_screen(*self.left_rim), to_screen(*self.right_rim)
            y_dim = 12.0
            for p in (a, b):
                painter.drawLine(QPointF(p.x(), y_dim - 4), QPointF(p.x(), p.y()))
            painter.drawLine(QPointF(a.x(), y_dim), QPointF(b.x(), y_dim))
            width_mm = (self.right_rim[0] - self.left_rim[0]) * mm
            label = f"{width_mm:.2f} mm"
            rect = QRectF((a.x() + b.x()) / 2 - 40, y_dim - 7, 80, 14)
            painter.fillRect(rect, theme.color(theme.PANEL))
            painter.setPen(theme.color(theme.TEXT))
            painter.drawText(rect, Qt.AlignCenter, label)
        if self.deepest and self.deepest_baseline_y is not None:
            top = to_screen(self.deepest[0], self.deepest_baseline_y)
            bottom = to_screen(*self.deepest)
            painter.setPen(QPen(theme.color(theme.MUTED), 1))
            painter.drawLine(top, bottom)
            painter.drawLine(QPointF(bottom.x() - 8, bottom.y()), QPointF(bottom.x() + 8, bottom.y()))
            depth_mm = (self.deepest[1] - self.deepest_baseline_y) * mm
            painter.setPen(theme.color(theme.TEXT))
            painter.drawText(QPointF(bottom.x() + 10, (top.y() + bottom.y()) / 2 + 4), f"{depth_mm:.2f} mm")

        painter.setPen(theme.color(theme.DIM))
        painter.drawText(
            QRectF(0, 2, self.width() - 6, 12), Qt.AlignRight, f"section · vertical ×{sy / sx:.1f}"
        )
        if self._hover_x is not None:
            source_x = x0 + (self._hover_x - 8.0) / sx
            xs = np.asarray([p[0] for p in self.profile])
            ys = np.asarray([p[1] for p in self.profile])
            if xs.min() <= source_x <= xs.max():
                y = float(np.interp(source_x, xs, ys))
                text = f"x {source_x * mm:.2f} mm"
                if self.baseline:
                    bx = np.asarray([p[0] for p in self.baseline])
                    by = np.asarray([p[1] for p in self.baseline])
                    if bx.min() <= source_x <= bx.max():
                        text += f"  ·  depth {(y - float(np.interp(source_x, bx, by))) * mm:.2f} mm"
                painter.setPen(QPen(theme.color(theme.ACCENT, 160), 1))
                painter.drawLine(QPointF(self._hover_x, 18), QPointF(self._hover_x, self.height()))
                painter.setPen(theme.color(theme.TEXT))
                painter.drawText(QRectF(6, 2, 400, 12), Qt.AlignLeft, text)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        self._hover_x = event.position().x()
        self.update()

    def leaveEvent(self, event) -> None:  # type: ignore[override]
        self._hover_x = None
        self.update()
