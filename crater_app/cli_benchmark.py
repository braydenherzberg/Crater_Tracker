from __future__ import annotations

import argparse
import csv
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

from crater_app.core.benchmark import (
    compare_summaries,
    load_labels,
    results_as_rows,
    run_benchmark,
    summarize,
)
from crater_app.core.video_reader import VideoReader
from crater_app.desktop.sessions import default_session_dir

DEFAULT_OUT = Path("local_analysis") / "benchmark"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Score guided crater tracking against labeled ground-truth sessions."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_sessions(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--sessions",
            nargs="*",
            default=None,
            help="Ground-truth session files (default: gt_*.json in the app's session library)",
        )

    status = sub.add_parser("status", help="List labeled frames per video")
    add_sessions(status)

    run = sub.add_parser("run", help="Run the benchmark and compare with the saved baseline")
    add_sessions(run)
    run.add_argument("--out", default=str(DEFAULT_OUT), help="Benchmark output folder")
    run.add_argument("--clicks", type=int, default=7, help="Simulated operator clicks per frame")
    run.add_argument("--noise-px", type=float, default=4.0, help="Simulated click noise (pixels)")
    run.add_argument(
        "--stabilize",
        action="store_true",
        help="Analyze a 7-frame temporal median instead of the raw frame",
    )
    run.add_argument(
        "--save-baseline",
        action="store_true",
        help="Store this run's summary as the baseline future runs compare against",
    )
    return parser.parse_args()


def session_paths(explicit: Optional[List[str]]) -> List[Path]:
    if explicit:
        return [Path(p).expanduser() for p in explicit]
    return sorted(default_session_dir().glob("gt_*.json"))


class FrameCache:
    def __init__(self, stabilize: bool) -> None:
        self.stabilize = stabilize
        self.readers: Dict[str, VideoReader] = {}

    def __call__(self, video_path: str, frame_index: int) -> Optional[np.ndarray]:
        if not Path(video_path).exists():
            return None
        reader = self.readers.get(video_path)
        if reader is None:
            reader = self.readers[video_path] = VideoReader(video_path)
        if not self.stabilize:
            return reader.get_frame_copy(frame_index)
        # Same offsets the desktop app uses for its stabilized review frame.
        frames = [
            reader.get_frame_copy(min(reader.frame_count - 1, max(0, frame_index + offset)))
            for offset in (-12, -8, -4, 0, 4, 8, 12)
        ]
        frames = [f for f in frames if f is not None]
        if not frames:
            return None
        return np.median(np.stack(frames), axis=0).astype(np.uint8)

    def close(self) -> None:
        for reader in self.readers.values():
            reader.release()


def cmd_status(args: argparse.Namespace) -> int:
    paths = session_paths(args.sessions)
    if not paths:
        print(f"No ground-truth sessions found (looked for gt_*.json in {default_session_dir()}).")
        return 1
    labels = load_labels(paths)
    by_video: Dict[str, List[int]] = {}
    for label in labels:
        by_video.setdefault(label.video_path, []).append(label.frame_index)
    for video, frames in by_video.items():
        exists = "" if Path(video).exists() else "  [VIDEO NOT FOUND]"
        print(f"{Path(video).name}: {len(frames)} labeled frame(s){exists}")
        print("  frames: " + ", ".join(f"{f:,}" for f in frames))
        if len(frames) < 3:
            print("  (needs 3+ labels for the interpolation test)")
    print(f"\nTotal: {len(labels)} labeled frame(s) from {len(paths)} session(s).")
    return 0


def fmt(value: float) -> str:
    return f"{value:8.2f}" if np.isfinite(value) else "     n/a"


def cmd_run(args: argparse.Namespace) -> int:
    paths = session_paths(args.sessions)
    labels = load_labels(paths)
    if not labels:
        print("No labeled frames found. Run `python3 -m crater_app.cli_benchmark status` for details.")
        return 1

    loader = FrameCache(args.stabilize)
    try:
        results = run_benchmark(
            labels,
            loader,
            clicks=args.clicks,
            noise_px=args.noise_px,
            progress=lambda msg: print(f"  {msg}"),
        )
    finally:
        loader.close()
    if not results:
        print("No frames could be read. Check that the session video paths exist.")
        return 1

    summary = summarize(results)
    out_root = Path(args.out)
    run_dir = out_root / datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    rows = results_as_rows(results)
    with (run_dir / "cases.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    report = {
        "created": datetime.now().isoformat(timespec="seconds"),
        "sessions": [str(p) for p in paths],
        "labeled_frames": len(labels),
        "clicks": args.clicks,
        "noise_px": args.noise_px,
        "stabilize": args.stabilize,
        "summary": summary,
    }
    (run_dir / "summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"\n{'group':<24}{'cases':>6}{'curve':>9}{'p95':>9}{'width':>9}{'depth':>9}{'rims':>9}{'missed':>8}")
    for group, m in summary.items():
        print(
            f"{group:<24}{int(m['cases']):>6}{fmt(m['curve_mae_px'])}{fmt(m['curve_p95_px'])}"
            f"{fmt(m['width_abs_err_px'])}{fmt(m['depth_abs_err_px'])}"
            f"{fmt(m['rim_abs_err_px'])}{m['missed_rate']:>8.0%}"
        )
    print("(mean absolute errors in pixels; lower is better)")

    baseline_path = out_root / "baseline.json"
    if baseline_path.exists() and not args.save_baseline:
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        if baseline.get("labeled_frames") != len(labels):
            print(
                f"\nNote: baseline used {baseline.get('labeled_frames')} labeled frames, "
                f"this run used {len(labels)}. Re-save the baseline before comparing."
            )
        print("\nCompared with baseline:")
        for line in compare_summaries(summary, baseline.get("summary", {})):
            print(line)
    if args.save_baseline:
        shutil.copyfile(run_dir / "summary.json", baseline_path)
        print(f"\nSaved as baseline: {baseline_path}")
    print(f"\nDetails: {run_dir}")
    return 0


def main() -> int:
    args = parse_args()
    if args.command == "status":
        return cmd_status(args)
    return cmd_run(args)


if __name__ == "__main__":
    raise SystemExit(main())
