"""Two-level timeline: whole run on top, a zoomable window below."""

from __future__ import annotations

from typing import Iterable, Optional

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from . import theme

OVERVIEW_H = 18
GAP = 8
LABEL_H = 13


def _nice_step(span: float, target_ticks: int = 6) -> int:
    raw = max(1.0, span / target_ticks)
    magnitude = 10 ** int(np.floor(np.log10(raw)))
    for factor in (1, 2, 5, 10):
        if raw <= factor * magnitude:
            return int(factor * magnitude)
    return int(10 * magnitude)


class Timeline(QWidget):
    seekRequested = Signal(int)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(OVERVIEW_H + GAP + 40 + LABEL_H)
        self.setMouseTracking(True)
        self.frame_count = 0
        self.fps = 30.0
        self.current = 0
        self.keyframes: list[int] = []
        self.activity_frames: Optional[np.ndarray] = None
        self.activity: Optional[np.ndarray] = None
        self.event_frame: Optional[int] = None
        self.settled_frame: Optional[int] = None
        self.busy_text: Optional[str] = None
        # background tracking pass: (frames, edge support 0..1, width px or nan)
        self.track_frames: Optional[np.ndarray] = None
        self.track_support: Optional[np.ndarray] = None
        self.track_width: Optional[np.ndarray] = None
        self.weak_threshold = 0.3
        self._start = 0
        self._span = 1
        self._drag_area: Optional[str] = None
        self._hover: Optional[int] = None

    # ------------------------------------------------------------------ data
    def set_video(self, frame_count: int, fps: float) -> None:
        self.frame_count = max(1, frame_count)
        self.fps = fps
        self.activity_frames = self.activity = None
        self.event_frame = self.settled_frame = None
        self._span = min(self.frame_count, max(200, int(fps * 8)))
        self._start = 0
        self.update()

    def set_current(self, frame: int) -> None:
        self.current = frame
        if not (self._start <= frame < self._start + self._span):
            self._center_on(frame)
        self.update()

    def set_keyframes(self, frames: Iterable[int]) -> None:
        self.keyframes = sorted(frames)
        self.update()

    def set_activity(self, frames, values, event_frame, settled_frame) -> None:
        self.activity_frames = None if frames is None else np.asarray(frames)
        self.activity = None if values is None else np.asarray(values)
        self.event_frame, self.settled_frame = event_frame, settled_frame
        self.update()

    def set_tracking(self, frames, support, width) -> None:
        if frames is None or len(frames) == 0:
            self.track_frames = self.track_support = self.track_width = None
        else:
            self.track_frames = np.asarray(frames)
            self.track_support = np.asarray(support, dtype=np.float64)
            self.track_width = np.asarray(width, dtype=np.float64)
        self.update()

    def set_busy(self, text: Optional[str]) -> None:
        self.busy_text = text
        self.update()

    def _center_on(self, frame: int) -> None:
        self._start = int(min(max(0, frame - self._span // 2), max(0, self.frame_count - self._span)))

    # --------------------------------------------------------------- geometry
    def _overview_rect(self) -> QRectF:
        return QRectF(0, 0, self.width(), OVERVIEW_H)

    def _zoom_rect(self) -> QRectF:
        top = OVERVIEW_H + GAP
        return QRectF(0, top, self.width(), self.height() - top - LABEL_H)

    def _x_overview(self, frame: float) -> float:
        return frame / max(1, self.frame_count - 1) * self.width()

    def _x_zoom(self, frame: float) -> float:
        return (frame - self._start) / max(1, self._span) * self.width()

    def _frame_at(self, x: float, area: str) -> int:
        if area == "overview":
            frame = x / max(1, self.width()) * (self.frame_count - 1)
        else:
            frame = self._start + x / max(1, self.width()) * self._span
        return int(round(min(max(0, frame), self.frame_count - 1)))

    # --------------------------------------------------------------- painting
    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setFont(theme.mono_font(9))
        ov, zr = self._overview_rect(), self._zoom_rect()
        painter.fillRect(ov, theme.color(theme.LINE))
        if self.frame_count <= 1:
            return

        # activity sparkline in both lanes
        if self.activity is not None and self.activity_frames is not None and len(self.activity):
            for lane, to_x in ((ov, self._x_overview), (zr, self._x_zoom)):
                path = QPainterPath(QPointF(to_x(self.activity_frames[0]), lane.bottom()))
                for f, v in zip(self.activity_frames, self.activity):
                    path.lineTo(QPointF(to_x(f), lane.bottom() - float(v) * (lane.height() - 2)))
                path.lineTo(QPointF(to_x(self.activity_frames[-1]), lane.bottom()))
                painter.save()
                painter.setClipRect(lane)
                painter.fillPath(path, theme.color(theme.MUTED, 70 if lane is ov else 40))
                painter.restore()

        # zoom lane frame + ticks
        painter.setPen(QPen(theme.color(theme.LINE_STRONG), 1))
        mid = zr.center().y()
        painter.drawLine(QPointF(0, mid), QPointF(self.width(), mid))
        step = _nice_step(self._span)
        first = (self._start // step + 1) * step
        painter.setPen(theme.color(theme.MUTED))
        for f in range(first, self._start + self._span, step):
            x = self._x_zoom(f)
            painter.drawLine(QPointF(x, zr.top()), QPointF(x, zr.top() + 5))
            painter.drawText(QPointF(x + 3, zr.top() + 11), f"{f:,}")

        # keyframe coverage (interpolated span) and markers
        if self.keyframes:
            a, b = self.keyframes[0], self.keyframes[-1]
            painter.setPen(QPen(theme.color(theme.ACCENT, 110), 3))
            painter.drawLine(QPointF(self._x_zoom(a), mid), QPointF(self._x_zoom(b), mid))
            painter.setPen(QPen(theme.color(theme.ACCENT), 2))
            for k in self.keyframes:
                x = self._x_overview(k)
                painter.drawLine(QPointF(x, 2), QPointF(x, OVERVIEW_H - 2))
            painter.setPen(Qt.NoPen)
            painter.setBrush(theme.color(theme.ACCENT))
            for k in self.keyframes:
                if self._start <= k <= self._start + self._span:
                    x = self._x_zoom(k)
                    painter.drawPolygon(
                        QPolygonF([QPointF(x, mid - 6), QPointF(x + 6, mid), QPointF(x, mid + 6), QPointF(x - 6, mid)])
                    )
            painter.setBrush(Qt.NoBrush)

        # tracking pass: edge-support bars (amber where weak) and width trace
        if self.track_frames is not None and len(self.track_frames):
            lane_top, lane_bottom = mid + 8, zr.bottom() - 1
            lane_h = max(4.0, lane_bottom - lane_top)
            gap = np.median(np.diff(self.track_frames)) if len(self.track_frames) > 1 else 1
            bar_w = max(1.0, self._x_zoom(self._start + gap) - self._x_zoom(self._start) - 1)
            for f, s_ in zip(self.track_frames, self.track_support):
                if not (self._start <= f <= self._start + self._span):
                    continue
                x = self._x_zoom(f)
                weak = not np.isfinite(s_) or s_ < self.weak_threshold
                h = lane_h * (0.25 if not np.isfinite(s_) else max(0.15, float(s_)))
                painter.fillRect(
                    QRectF(x - bar_w / 2, lane_bottom - h, bar_w, h),
                    theme.color(theme.ACCENT if weak else theme.MUTED, 200 if weak else 110),
                )
            widths = self.track_width
            finite = np.isfinite(widths)
            if finite.sum() >= 2:
                lo, hi = np.nanmin(widths), np.nanmax(widths)
                span_w = max(1e-6, hi - lo)
                path = QPainterPath()
                started = False
                for f, w_ in zip(self.track_frames, widths):
                    if not np.isfinite(w_):
                        started = False
                        continue
                    pt = QPointF(self._x_zoom(f), zr.top() + 16 + (1 - (w_ - lo) / span_w) * (mid - zr.top() - 20))
                    if started:
                        path.lineTo(pt)
                    else:
                        path.moveTo(pt)
                        started = True
                painter.save()
                painter.setClipRect(zr)
                painter.setPen(QPen(theme.color(theme.TEXT, 150), 1))
                painter.drawPath(path)
                painter.restore()
            for f, s_ in zip(self.track_frames, self.track_support):
                if not np.isfinite(s_) or s_ < self.weak_threshold:
                    x = self._x_overview(f)
                    painter.setPen(QPen(theme.color(theme.ACCENT, 150), 1))
                    painter.drawLine(QPointF(x, OVERVIEW_H - 5), QPointF(x, OVERVIEW_H))

        # event / settled markers
        for frame, label in ((self.event_frame, "event"), (self.settled_frame, "settled")):
            if frame is None:
                continue
            painter.setPen(QPen(theme.color(theme.MUTED), 1, Qt.DashLine))
            x = self._x_overview(frame)
            painter.drawLine(QPointF(x, 0), QPointF(x, OVERVIEW_H))
            if self._start <= frame <= self._start + self._span:
                xz = self._x_zoom(frame)
                painter.drawLine(QPointF(xz, zr.top() + 14), QPointF(xz, zr.bottom()))
                painter.setPen(theme.color(theme.MUTED))
                painter.drawText(QPointF(xz + 3, zr.bottom() - 2), label)

        # zoom window on the overview
        painter.setPen(QPen(theme.color(theme.TEXT, 160), 1))
        x0, x1 = self._x_overview(self._start), self._x_overview(self._start + self._span)
        painter.drawRect(QRectF(x0, 0.5, max(2.0, x1 - x0), OVERVIEW_H - 1))

        # playhead
        painter.setPen(QPen(theme.color(theme.TEXT), 1.5))
        xo = self._x_overview(self.current)
        painter.drawLine(QPointF(xo, 0), QPointF(xo, OVERVIEW_H))
        xz = self._x_zoom(self.current)
        painter.drawLine(QPointF(xz, zr.top()), QPointF(xz, zr.bottom()))

        # footer: range and hover / busy text
        painter.setPen(theme.color(theme.MUTED))
        footer = QRectF(0, self.height() - LABEL_H, self.width(), LABEL_H)
        end = self._start + self._span - 1
        painter.drawText(
            footer,
            Qt.AlignLeft | Qt.AlignVCenter,
            f"view {self._start:,}–{end:,}  ·  {self._span / self.fps:.1f} s  ·  scroll to zoom",
        )
        right = self.busy_text or (f"frame {self._hover:,}" if self._hover is not None else "")
        painter.drawText(footer, Qt.AlignRight | Qt.AlignVCenter, right)

    # ------------------------------------------------------------------ input
    def _area_at(self, y: float) -> str:
        return "overview" if y <= OVERVIEW_H + GAP / 2 else "zoom"

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if self.frame_count <= 1 or event.button() != Qt.LeftButton:
            return
        self._drag_area = self._area_at(event.position().y())
        self._seek_from(event.position().x())

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if self.frame_count <= 1:
            return
        area = self._area_at(event.position().y())
        self._hover = self._frame_at(event.position().x(), area)
        if self._drag_area is not None:
            self._seek_from(event.position().x())
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        self._drag_area = None

    def leaveEvent(self, event) -> None:  # type: ignore[override]
        self._hover = None
        self.update()

    def _seek_from(self, x: float) -> None:
        frame = self._frame_at(x, self._drag_area or "zoom")
        if self._drag_area == "overview":
            self._center_on(frame)
        self.seekRequested.emit(frame)

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        if self.frame_count <= 1:
            return
        delta = event.angleDelta()
        if abs(delta.x()) > abs(delta.y()):  # horizontal scroll pans
            shift = int(-delta.x() / 120.0 * self._span * 0.1)
            self._start = int(min(max(0, self._start + shift), max(0, self.frame_count - self._span)))
        else:
            anchor = self._frame_at(event.position().x(), "zoom")
            fraction = event.position().x() / max(1, self.width())
            span = int(self._span * (0.8 ** (delta.y() / 120.0)))
            self._span = int(min(self.frame_count, max(60, span)))
            self._start = int(
                min(max(0, anchor - fraction * self._span), max(0, self.frame_count - self._span))
            )
        self.update()
