"""Headless time-series export from a saved session.

    python -m crater_app.cli_batch --session ~/.crater_analysis/sessions/gt_MP_Run3.json \
        --out mp3_series.csv --frame-step 10 [--profiles] [--video /new/path.mp4]
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from crater_app import __version__
from crater_app.core.series import SERIES_FIELDS, keyframe_span, measure_series
from crater_app.core.session import Calibration, load_session_file
from crater_app.core.video_reader import VideoReader


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export a crater time series from a saved session.")
    parser.add_argument("--session", required=True, help="Session JSON saved by the desktop app")
    parser.add_argument("--out", required=True, help="Output CSV file")
    parser.add_argument("--video", default="", help="Video path, if it moved since the session was saved")
    parser.add_argument("--frame-step", type=int, default=10, help="Measure every Nth frame (keyframes always included)")
    parser.add_argument("--profiles", action="store_true", help="Also write <out>_profiles.csv with every profile point")
    parser.add_argument("--no-snap", action="store_true", help="Measure the operator lines without edge refinement")
    parser.add_argument("--frame-width-mm", type=float, default=0.0, help="Override calibration: full-frame width in mm")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    session = load_session_file(Path(args.session).expanduser())
    video_path = args.video or session.video_path
    if not video_path or not Path(video_path).exists():
        print(f"Video not found: {video_path!r}. Pass --video.", file=sys.stderr)
        return 2
    span = keyframe_span(session.keyframes)
    if span is None:
        print("The session has no keyframes with at least three points.", file=sys.stderr)
        return 2
    reader = VideoReader(video_path)
    fps, width = reader.fps, reader.width
    reader.release()
    if args.frame_width_mm > 0:
        calibration = Calibration.from_frame_width(args.frame_width_mm, width)
    elif session.calibration is not None:
        calibration = session.calibration
    else:
        print("The session has no calibration. Pass --frame-width-mm.", file=sys.stderr)
        return 2

    def progress(fraction: float) -> None:
        print(f"\r  measuring {fraction:5.1%}", end="", file=sys.stderr, flush=True)

    rows, profiles = measure_series(
        video_path,
        session.keyframes,
        start=span[0],
        stop=span[1],
        step=args.frame_step,
        fps=fps,
        mm_per_px=calibration.mm_per_px,
        snap=not args.no_snap,
        include_profiles=args.profiles,
        progress=progress,
    )
    print(file=sys.stderr)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SERIES_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    if profiles:
        with out.with_name(out.stem + "_profiles.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(profiles[0].keys()))
            writer.writeheader()
            writer.writerows(profiles)
    meta = {
        "app_version": __version__,
        "video": video_path,
        "frame_step": args.frame_step,
        "snap_to_edge": not args.no_snap,
        "mm_per_px": calibration.mm_per_px,
        "session": str(Path(args.session).expanduser()),
    }
    out.with_name(out.stem + "_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"Wrote {len(rows)} rows to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
