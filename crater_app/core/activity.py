"""Whole-run activity scan used to find the experiment event.

The scan decodes the video in order, keeps a small grey thumbnail every
``step`` frames and measures how much each thumbnail differs from the
previous one. The experiment (plume, ejecta, dust) is the first sustained
spike; the crater is best reviewed once activity settles again.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

import cv2
import numpy as np

from .video_reader import iter_frames


@dataclass
class ActivityScan:
    frames: np.ndarray  # sampled frame indices
    activity: np.ndarray  # 0..1, normalised change versus the previous sample
    event_frame: Optional[int]
    settled_frame: Optional[int]


def _robust_threshold(values: np.ndarray, k: float) -> float:
    median = float(np.median(values))
    mad = float(np.median(np.abs(values - median))) + 1e-6
    return median + k * 1.4826 * mad


def analyze_activity(
    frames: np.ndarray, raw: np.ndarray, window_frames: int = 480
) -> ActivityScan:
    """Locate the event and the settled frame from a raw activity trace.

    The event is the strongest sustained burst (most activity within
    ``window_frames``), not merely the first spike: camera handling and
    lighting changes produce short spikes, whereas the plume and ejecta keep
    the scene moving for seconds.
    """

    if len(raw) < 8:
        norm = raw / (raw.max() + 1e-6) if len(raw) else raw
        return ActivityScan(frames, norm, None, None)
    ceiling = float(np.percentile(raw, 99.5)) + 1e-6
    norm = np.clip(raw / ceiling, 0.0, 1.0)
    step = max(1, int(frames[1] - frames[0]))
    window = max(3, int(round(window_frames / step)))
    window = min(window, len(raw))
    energy = np.convolve(raw, np.ones(window), "valid")
    window_start = int(np.argmax(energy))
    burst = raw[window_start : window_start + window]
    event_threshold = _robust_threshold(raw, 8.0)
    if burst.max() <= event_threshold:
        return ActivityScan(frames, norm, None, None)
    event_pos = window_start + int(np.argmax(burst > event_threshold))
    peak_pos = window_start + int(np.argmax(burst))
    # Settled: the first run of quiet samples after the burst's peak.
    quiet_threshold = _robust_threshold(raw, 3.0)
    settled_pos = None
    run = 0
    for pos in range(peak_pos, len(raw)):
        run = run + 1 if raw[pos] <= quiet_threshold else 0
        if run >= 4:
            settled_pos = pos - 3
            break
    return ActivityScan(
        frames,
        norm,
        int(frames[event_pos]),
        int(frames[settled_pos]) if settled_pos is not None else None,
    )


def scan_activity(
    video_path: str,
    frame_count: int,
    *,
    samples: int = 600,
    progress: Optional[Callable[[float], None]] = None,
    cancelled: Optional[Callable[[], bool]] = None,
) -> Optional[ActivityScan]:
    step = max(1, frame_count // max(1, samples))
    indices = []
    raw = []
    previous = None
    for index, frame in iter_frames(video_path, 0, frame_count - 1, step):
        if cancelled is not None and cancelled():
            return None
        thumb = cv2.resize(frame, (160, 90), interpolation=cv2.INTER_AREA)
        thumb = cv2.GaussianBlur(cv2.cvtColor(thumb, cv2.COLOR_BGR2GRAY), (5, 5), 0).astype(np.float32)
        if previous is not None:
            delta = thumb - previous
            delta -= float(np.median(delta))  # ignore global exposure drift
            indices.append(index)
            raw.append(float(np.mean(np.abs(delta))))
        previous = thumb
        if progress is not None:
            progress(min(1.0, index / max(1, frame_count - 1)))
    return analyze_activity(np.asarray(indices, dtype=np.int64), np.asarray(raw, dtype=np.float64))
