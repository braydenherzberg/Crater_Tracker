"""Video canvas: frame display, overlays, point editing, zoom and a loupe."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional, Sequence, Tuple

import cv2
import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QImage, QPainter, QPainterPath, QPen, QTransform
from PySide6.QtWidgets import QWidget

from . import theme

Point = Tuple[float, float]

LOUPE_SIZE = 200
LOUPE_ZOOM = 5.0
HIT_RADIUS = 9.0


@dataclass
class Overlays:
    clicks: List[Point] = field(default_factory=list)
    clicks_are_keyframe: bool = False
    guide: List[Point] = field(default_factory=list)  # interpolated guide
    tracked: List[Point] = field(default_factory=list)
    baseline: List[Point] = field(default_factory=list)
    left_rim: Optional[Point] = None
    right_rim: Optional[Point] = None
    deepest: Optional[Point] = None
    deepest_baseline_y: Optional[float] = None


class FrameCanvas(QWidget):
    """Shows one frame. In edit mode clicks add, drag moves, right-click deletes."""

    pointsEdited = Signal(list)
    calibrationPicked = Signal(tuple, tuple)
    cursorMoved = Signal(float, float)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.ClickFocus)
        self.setMinimumSize(320, 200)
        self._image: Optional[QImage] = None
        self._image_size = (0, 0)
        self.overlays = Overlays()
        self.show_clicks = True
        self.show_tracked = True
        self.show_geometry = True
        self.mode = "view"  # "view", "edit", "calibrate"
        self._zoom = 1.0
        self._center: Optional[QPointF] = None
        self._cursor: Optional[QPointF] = None  # widget coords
        self._drag_index: Optional[int] = None
        self._drag_points: Optional[List[Point]] = None
        self._pan_origin: Optional[Tuple[QPointF, QPointF]] = None
        self._calibration: List[Point] = []
        self.placeholder = "Open a video to begin  (⌘O / Ctrl+O)"

    # ----------------------------------------------------------------- data
    def set_frame(self, bgr: Optional[np.ndarray]) -> None:
        if bgr is None:
            self._image = None
            self._image_size = (0, 0)
        else:
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            h, w = rgb.shape[:2]
            self._image = QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888).copy()
            if self._image_size != (w, h):
                self._zoom, self._center = 1.0, None
            self._image_size = (w, h)
        self.update()

    def set_overlays(self, overlays: Overlays) -> None:
        self.overlays = overlays
        self.update()

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self._calibration = []
        self._drag_index = None
        self.setCursor(Qt.CrossCursor if mode in ("edit", "calibrate") else Qt.ArrowCursor)
        self.update()

    def reset_view(self) -> None:
        self._zoom, self._center = 1.0, None
        self.update()

    # ------------------------------------------------------------ transforms
    def _scale_offset(self) -> Tuple[float, QPointF]:
        iw, ih = self._image_size
        if iw <= 0 or ih <= 0:
            return 1.0, QPointF(0, 0)
        fit = min(self.width() / iw, self.height() / ih)
        scale = fit * self._zoom
        center = self._center or QPointF(iw / 2, ih / 2)
        # Keep the image covering the view when zoomed in.
        half_w, half_h = self.width() / (2 * scale), self.height() / (2 * scale)
        cx = min(max(center.x(), min(half_w, iw / 2)), max(iw - half_w, iw / 2))
        cy = min(max(center.y(), min(half_h, ih / 2)), max(ih - half_h, ih / 2))
        offset = QPointF(self.width() / 2 - cx * scale, self.height() / 2 - cy * scale)
        return scale, offset

    def to_widget(self, x: float, y: float) -> QPointF:
        scale, offset = self._scale_offset()
        return QPointF(offset.x() + x * scale, offset.y() + y * scale)

    def to_source(self, p: QPointF) -> Point:
        scale, offset = self._scale_offset()
        return ((p.x() - offset.x()) / scale, (p.y() - offset.y()) / scale)

    def _inside(self, x: float, y: float) -> bool:
        iw, ih = self._image_size
        return 0 <= x < iw and 0 <= y < ih

    # --------------------------------------------------------------- painting
    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.fillRect(self.rect(), theme.color("#000000"))
        if self._image is None:
            painter.setPen(theme.color(theme.MUTED))
            painter.drawText(self.rect(), Qt.AlignCenter, self.placeholder)
            return
        scale, offset = self._scale_offset()
        painter.save()
        painter.setRenderHint(QPainter.SmoothPixmapTransform, scale < 2.0)
        painter.setTransform(QTransform(scale, 0, 0, scale, offset.x(), offset.y()))
        painter.drawImage(0, 0, self._image)
        painter.restore()
        painter.setRenderHint(QPainter.Antialiasing, True)
        self._draw_overlays(painter, self.to_widget, point_radius=4.5)
        if self._cursor is not None and self.mode in ("edit", "calibrate"):
            self._draw_loupe(painter)

    def _draw_overlays(
        self,
        painter: QPainter,
        to_screen: Callable[[float, float], QPointF],
        point_radius: float,
        line_scale: float = 1.0,
    ) -> None:
        o = self.overlays

        def path_of(points: Sequence[Point]) -> QPainterPath:
            path = QPainterPath()
            for i, (x, y) in enumerate(points):
                p = to_screen(x, y)
                path.moveTo(p) if i == 0 else path.lineTo(p)
            return path

        if self.show_geometry and o.baseline:
            pen = QPen(theme.color(theme.TEXT, 200), 1.0 * line_scale, Qt.DashLine)
            painter.setPen(pen)
            painter.drawLine(to_screen(*o.baseline[0]), to_screen(*o.baseline[-1]))
        if self.show_tracked and len(o.tracked) > 1:
            painter.setPen(QPen(theme.color(theme.TEXT, 235), 1.6 * line_scale))
            painter.drawPath(path_of(o.tracked))
        if self.show_geometry:
            painter.setPen(QPen(theme.color(theme.TEXT), 1.4 * line_scale))
            for rim in (o.left_rim, o.right_rim):
                if rim is not None:
                    p = to_screen(*rim)
                    painter.drawLine(QPointF(p.x(), p.y() - 16 * line_scale), QPointF(p.x(), p.y() + 16 * line_scale))
            if o.deepest is not None and o.deepest_baseline_y is not None:
                top = to_screen(o.deepest[0], o.deepest_baseline_y)
                bottom = to_screen(*o.deepest)
                painter.drawLine(top, bottom)
                painter.drawLine(QPointF(bottom.x() - 6, bottom.y()), QPointF(bottom.x() + 6, bottom.y()))
        if self.show_clicks and len(o.guide) > 1:
            painter.setPen(QPen(theme.color(theme.ACCENT, 170), 1.0 * line_scale, Qt.DotLine))
            painter.drawPath(path_of(o.guide))
        points = self._drag_points if self._drag_points is not None else o.clicks
        if self.show_clicks and points:
            accent = theme.color(theme.ACCENT)
            painter.setPen(QPen(accent, 1.0 * line_scale, Qt.SolidLine if o.clicks_are_keyframe else Qt.DashLine))
            if len(points) > 1:
                painter.drawPath(path_of(points))
            painter.setPen(QPen(accent, 2.0))
            painter.setBrush(theme.color(theme.BG) if o.clicks_are_keyframe else theme.color(theme.ACCENT, 60))
            for x, y in points:
                painter.drawEllipse(to_screen(x, y), point_radius, point_radius)
            painter.setBrush(Qt.NoBrush)
        if self._calibration:
            painter.setPen(QPen(theme.color("#7fd1c7"), 1.5))
            pts = [to_screen(x, y) for x, y in self._calibration]
            for p in pts:
                painter.drawLine(QPointF(p.x() - 8, p.y()), QPointF(p.x() + 8, p.y()))
                painter.drawLine(QPointF(p.x(), p.y() - 8), QPointF(p.x(), p.y() + 8))
            if len(pts) == 1 and self._cursor is not None:
                painter.drawLine(pts[0], self._cursor)

    def _draw_loupe(self, painter: QPainter) -> None:
        sx, sy = self.to_source(self._cursor)
        if not self._inside(sx, sy):
            return
        margin = 12
        on_left = self._cursor.x() < self.width() / 2
        left = self.width() - LOUPE_SIZE - margin if on_left else margin
        rect = QRectF(left, margin, LOUPE_SIZE, LOUPE_SIZE)
        center = rect.center()

        def to_loupe(x: float, y: float) -> QPointF:
            return QPointF(center.x() + (x - sx) * LOUPE_ZOOM, center.y() + (y - sy) * LOUPE_ZOOM)

        painter.save()
        painter.setClipRect(rect)
        painter.fillRect(rect, theme.color("#000000"))
        painter.setRenderHint(QPainter.SmoothPixmapTransform, False)
        painter.setTransform(
            QTransform(LOUPE_ZOOM, 0, 0, LOUPE_ZOOM, center.x() - sx * LOUPE_ZOOM, center.y() - sy * LOUPE_ZOOM)
        )
        painter.drawImage(0, 0, self._image)
        painter.resetTransform()
        painter.setRenderHint(QPainter.Antialiasing, True)
        self._draw_overlays(painter, to_loupe, point_radius=5.0)
        painter.setPen(QPen(theme.color(theme.ACCENT, 200), 1.0))
        painter.drawLine(QPointF(center.x(), rect.top()), QPointF(center.x(), center.y() - 6))
        painter.drawLine(QPointF(center.x(), center.y() + 6), QPointF(center.x(), rect.bottom()))
        painter.drawLine(QPointF(rect.left(), center.y()), QPointF(center.x() - 6, center.y()))
        painter.drawLine(QPointF(center.x() + 6, center.y()), QPointF(rect.right(), center.y()))
        painter.restore()
        painter.setPen(QPen(theme.color(theme.LINE_STRONG), 1.0))
        painter.drawRect(rect)
        painter.setPen(theme.color(theme.TEXT))
        painter.setFont(theme.mono_font(10))
        painter.drawText(rect.adjusted(6, 0, -6, -4), Qt.AlignBottom | Qt.AlignLeft, f"{sx:.1f}, {sy:.1f}")

    def render_snapshot(self) -> Optional[QImage]:
        """Full-resolution frame with the current overlays burned in."""

        if self._image is None:
            return None
        image = self._image.copy()
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing, True)
        self._draw_overlays(painter, lambda x, y: QPointF(x, y), point_radius=6.0, line_scale=2.0)
        painter.end()
        return image

    # ------------------------------------------------------------------ input
    def _nearest_point(self, pos: QPointF) -> Optional[int]:
        best, best_d = None, HIT_RADIUS
        for i, (x, y) in enumerate(self.overlays.clicks):
            p = self.to_widget(x, y)
            d = ((p.x() - pos.x()) ** 2 + (p.y() - pos.y()) ** 2) ** 0.5
            if d <= best_d:
                best, best_d = i, d
        return best

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        pos = event.position()
        if event.button() == Qt.MiddleButton or (
            event.button() == Qt.LeftButton and event.modifiers() & Qt.AltModifier
        ):
            scale, offset = self._scale_offset()
            center = QPointF((self.width() / 2 - offset.x()) / scale, (self.height() / 2 - offset.y()) / scale)
            self._pan_origin = (pos, center)
            return
        if self._image is None:
            return
        sx, sy = self.to_source(pos)
        if self.mode == "calibrate" and event.button() == Qt.LeftButton and self._inside(sx, sy):
            self._calibration.append((round(sx, 1), round(sy, 1)))
            if len(self._calibration) == 2:
                a, b = self._calibration
                self._calibration = []
                self.calibrationPicked.emit(a, b)
            self.update()
            return
        if self.mode != "edit":
            return
        index = self._nearest_point(pos)
        if event.button() == Qt.RightButton:
            if index is not None:
                points = list(self.overlays.clicks)
                points.pop(index)
                self.pointsEdited.emit(points)
            return
        if event.button() != Qt.LeftButton or not self._inside(sx, sy):
            return
        if index is not None:
            self._drag_index = index
            self._drag_points = list(self.overlays.clicks)
            return
        points = sorted(list(self.overlays.clicks) + [(round(sx, 1), round(sy, 1))])
        self.pointsEdited.emit(points)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        pos = event.position()
        self._cursor = pos
        if self._pan_origin is not None:
            start, center = self._pan_origin
            scale, _ = self._scale_offset()
            self._center = QPointF(
                center.x() - (pos.x() - start.x()) / scale, center.y() - (pos.y() - start.y()) / scale
            )
        elif self._drag_index is not None and self._drag_points is not None:
            sx, sy = self.to_source(pos)
            iw, ih = self._image_size
            self._drag_points[self._drag_index] = (
                round(min(max(sx, 0), iw - 1), 1),
                round(min(max(sy, 0), ih - 1), 1),
            )
        sx, sy = self.to_source(pos)
        if self._inside(sx, sy):
            self.cursorMoved.emit(sx, sy)
        else:
            self.cursorMoved.emit(-1.0, -1.0)
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        if self._pan_origin is not None:
            self._pan_origin = None
            return
        if self._drag_index is not None and self._drag_points is not None:
            points = sorted(self._drag_points)
            self._drag_index = None
            self._drag_points = None
            self.pointsEdited.emit(points)

    def leaveEvent(self, event) -> None:  # type: ignore[override]
        self._cursor = None
        self.cursorMoved.emit(-1.0, -1.0)
        self.update()

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        if self._image is None:
            return
        steps = event.angleDelta().y() / 120.0
        if steps == 0:
            return
        pos = event.position()
        before = self.to_source(pos)
        self._zoom = float(min(16.0, max(1.0, self._zoom * (1.2**steps))))
        if self._zoom == 1.0:
            self._center = None
        else:
            scale, offset = self._scale_offset()
            # Keep the source point under the cursor fixed.
            current = self._center or QPointF(self._image_size[0] / 2, self._image_size[1] / 2)
            after = self.to_source(pos)
            self._center = QPointF(current.x() + before[0] - after[0], current.y() + before[1] - after[1])
        self.update()
