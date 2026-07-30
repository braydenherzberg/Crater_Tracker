from __future__ import annotations

import argparse
import json
from pathlib import Path

from crater_app.core.analysis import AnalysisEngine
from crater_app.core.settings import AnalysisSettings
from crater_app.core.video_reader import VideoReader
from crater_app.desktop.exporter import export_metrics_csv


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Batch crater metrics extraction.")
    parser.add_argument("--video", required=True, help="Input video path")
    parser.add_argument("--out", required=True, help="Output CSV file")
    parser.add_argument(
        "--settings-json",
        default="",
        help="Optional JSON file matching AnalysisSettings keys",
    )
    parser.add_argument(
        "--frame-step",
        type=int,
        default=1,
        help="Analyze every Nth frame (useful for long high-speed recordings)",
    )
    return parser.parse_args()


def load_settings(path: str) -> AnalysisSettings:
    if not path:
        return AnalysisSettings()
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return AnalysisSettings.from_dict(payload)


def main() -> int:
    args = parse_args()
    settings = load_settings(args.settings_json)
    engine = AnalysisEngine()
    reader = VideoReader(args.video)
    rows = []
    try:
        for idx in range(0, reader.frame_count, max(1, args.frame_step)):
            frame = reader.get_frame_copy(idx)
            if frame is None:
                continue
            result = engine.analyze_frame(frame, settings)
            m = result.metrics
            frame_width_px = frame.shape[1]
            mm_per_px = settings.real_width_mm / frame_width_px if frame_width_px > 0 else 0.0
            rows.append(
                {
                    "frame_index": idx,
                    "timestamp_ms": (idx / reader.fps) * 1000.0,
                    "detection_mode": result.detection_mode,
                    "status": result.status,
                    "avg_crater_width_mm": m.avg_crater_width_px * mm_per_px,
                    "max_crater_width_mm": m.max_crater_width_px * mm_per_px,
                    "trace_width_mm": m.trace_width_px * mm_per_px,
                    "max_crater_depth_mm": m.max_crater_depth_px * mm_per_px,
                    "crater_area_mm2": m.crater_area_px * (mm_per_px**2),
                    "point_count": m.point_count,
                    "confidence": m.confidence,
                    "baseline_tilt_degrees": m.baseline_tilt_degrees,
                }
            )
    finally:
        reader.release()

    export_metrics_csv(rows, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
