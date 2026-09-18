"""Session files: one video's keyframes and calibration.

Version 2 adds calibration. Unknown keys (for example ``starred_frames`` from
v0.3 sessions) are preserved untouched when a session is re-saved, so older
work is never silently dropped.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

Point = Tuple[float, float]
SESSION_VERSION = 2


@dataclass
class Calibration:
    mm_per_px: float
    method: str  # "frame_width" or "two_point"
    points: List[Point] = field(default_factory=list)
    known_mm: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mm_per_px": self.mm_per_px,
            "method": self.method,
            "points": [[round(x, 2), round(y, 2)] for x, y in self.points],
            "known_mm": self.known_mm,
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "Calibration":
        return cls(
            mm_per_px=float(payload["mm_per_px"]),
            method=str(payload.get("method", "frame_width")),
            points=[(float(p[0]), float(p[1])) for p in payload.get("points", [])],
            known_mm=payload.get("known_mm"),
        )

    @classmethod
    def from_frame_width(cls, width_mm: float, width_px: int) -> "Calibration":
        return cls(mm_per_px=width_mm / max(1, width_px), method="frame_width", known_mm=width_mm)


@dataclass
class Session:
    video_path: str
    keyframes: Dict[int, List[Point]] = field(default_factory=dict)
    calibration: Optional[Calibration] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> Dict[str, Any]:
        payload = dict(self.extra)
        payload.update(
            {
                "version": SESSION_VERSION,
                "video_path": self.video_path,
                "guide_keyframes": {
                    str(frame): [[round(x, 2), round(y, 2)] for x, y in points]
                    for frame, points in sorted(self.keyframes.items())
                },
                "calibration": self.calibration.to_dict() if self.calibration else None,
            }
        )
        return payload

    @classmethod
    def from_payload(cls, payload: Dict[str, Any]) -> "Session":
        keyframes = {
            int(frame): [(float(p[0]), float(p[1])) for p in points]
            for frame, points in (payload.get("guide_keyframes") or {}).items()
            if isinstance(points, list)
        }
        calibration = payload.get("calibration")
        extra = {
            k: v
            for k, v in payload.items()
            if k not in {"version", "video_path", "guide_keyframes", "calibration"}
        }
        return cls(
            video_path=str(payload.get("video_path") or ""),
            keyframes=keyframes,
            calibration=Calibration.from_dict(calibration) if calibration else None,
            extra=extra,
        )


def save_session_file(path: Path, session: Session) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(session.to_payload(), indent=2), encoding="utf-8")
    tmp.replace(path)


def load_session_file(path: Path) -> Session:
    return Session.from_payload(json.loads(Path(path).read_text(encoding="utf-8")))


def find_sessions_for_video(session_dir: Path, video_path: str) -> List[Path]:
    """Sessions whose recorded video is this file (by path, then by name)."""

    if not session_dir.exists():
        return []
    target = Path(video_path)
    exact, by_name = [], []
    for path in sorted(session_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            recorded = json.loads(path.read_text(encoding="utf-8")).get("video_path") or ""
        except (OSError, ValueError):
            continue
        if not recorded:
            continue
        if Path(recorded) == target:
            exact.append(path)
        elif Path(recorded).name == target.name:
            by_name.append(path)
    return exact + by_name
