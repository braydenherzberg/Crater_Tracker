from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class AnalysisSettings:
    threshold: int = 94
    smoothing: int = 15
    despeckle: int = 6
    tilt_degrees: float = 0.0
    channel: int = 0  # 0=gray, 1=blue, 2=green, 3=red
    zone_left: int = 150
    zone_right: int = 150
    surface_boundary: int = 200
    scan_mode: int = 1  # 1=bottom-up, 0=top-down
    left_margin: int = 100
    right_margin: int = 100
    top_margin: int = 50
    x_step: int = 5
    real_width_mm: float = 124.0

    def normalized(self, frame_height: int) -> "AnalysisSettings":
        smoothing = max(1, int(self.smoothing))
        despeckle = max(0, int(self.despeckle))
        if despeckle > 0 and despeckle % 2 == 0:
            despeckle += 1
        channel = int(min(3, max(0, self.channel)))
        scan_mode = 1 if int(self.scan_mode) == 1 else 0

        floor = int(self.surface_boundary)
        floor = max(0, min(frame_height - 1, floor))

        return AnalysisSettings(
            threshold=int(min(255, max(0, self.threshold))),
            smoothing=smoothing,
            despeckle=despeckle,
            tilt_degrees=float(min(7.0, max(-7.0, self.tilt_degrees))),
            channel=channel,
            zone_left=max(0, int(self.zone_left)),
            zone_right=max(0, int(self.zone_right)),
            surface_boundary=floor,
            scan_mode=scan_mode,
            left_margin=max(0, int(self.left_margin)),
            right_margin=max(0, int(self.right_margin)),
            top_margin=max(0, int(self.top_margin)),
            x_step=max(1, int(self.x_step)),
            real_width_mm=max(0.1, float(self.real_width_mm)),
        )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict) -> "AnalysisSettings":
        allowed = set(cls.__dataclass_fields__.keys())
        filtered = {k: v for k, v in payload.items() if k in allowed}
        return cls(**filtered)

