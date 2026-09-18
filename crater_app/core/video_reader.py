from __future__ import annotations

from collections import OrderedDict
from typing import Iterable, Iterator, Optional, Tuple

import cv2
import numpy as np

# Reading forward through a few frames is far cheaper than a random seek on
# long-GOP codecs (HEVC seeks on the supplied footage take ~150-200 ms, a
# sequential read ~1 ms), so short forward jumps decode instead of seeking.
FORWARD_READ_LIMIT = 90
# A backward step that misses the cache seeks once and fills this many frames.
BACKWARD_PREFETCH = 24


class VideoReader:
    """Random-access frame reader tuned for scrubbing high-speed footage.

    Not thread-safe: background jobs should open their own reader.
    """

    def __init__(self, video_path: str, max_cache_size: int = 150) -> None:
        self.video_path = video_path
        self.max_cache_size = max_cache_size
        self.cap = cv2.VideoCapture(video_path)
        if not self.cap.isOpened():
            raise RuntimeError(f"Could not open video: {video_path}")

        self.frame_count = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.fps = float(self.cap.get(cv2.CAP_PROP_FPS))
        if not np.isfinite(self.fps) or self.fps <= 0:
            self.fps = 30.0
        self.width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self._frames = None
        self._cache: "OrderedDict[int, np.ndarray]" = OrderedDict()
        self._next_index = 0  # index the capture will decode next

        if self.frame_count <= 0:
            self._frames = []
            while True:
                ok, frame = self.cap.read()
                if not ok:
                    break
                self._frames.append(frame)
            self.cap.release()
            self.frame_count = len(self._frames)
            if self.frame_count == 0:
                raise RuntimeError(f"No frames loaded from video: {video_path}")
        else:
            first = self.get_frame(0)
            if first is None:
                raise RuntimeError(f"Could not read first frame from video: {video_path}")
            self.height, self.width = first.shape[:2]

    def _remember(self, index: int, frame: np.ndarray) -> None:
        self._cache[index] = frame
        self._cache.move_to_end(index)
        while len(self._cache) > self.max_cache_size:
            self._cache.popitem(last=False)

    def _seek(self, index: int) -> None:
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, index)
        self._next_index = index

    def _read_next(self) -> Optional[np.ndarray]:
        ok, frame = self.cap.read()
        if not ok:
            return None
        index = self._next_index
        self._next_index += 1
        self._remember(index, frame)
        return frame

    def get_frame(self, index: int) -> Optional[np.ndarray]:
        if index < 0 or index >= self.frame_count:
            return None
        if self._frames is not None:
            return self._frames[index]
        if index in self._cache:
            self._cache.move_to_end(index)
            return self._cache[index]

        gap = index - self._next_index
        if 0 <= gap <= FORWARD_READ_LIMIT:
            for _ in range(gap):
                if not self.cap.grab():
                    break
                self._next_index += 1
            if self._next_index == index:
                frame = self._read_next()
                if frame is not None:
                    return frame
        elif gap < 0:
            # Stepping backwards: fill a block ending at the requested frame so
            # the next backward steps are cache hits.
            start = max(0, index - BACKWARD_PREFETCH + 1)
            self._seek(start)
            frame = None
            for _ in range(start, index + 1):
                frame = self._read_next()
                if frame is None:
                    break
            if frame is not None and self._next_index == index + 1:
                return frame

        self._seek(index)
        frame = self._read_next()
        if frame is None:
            # Random access can fail transiently on inter-frame codecs. Reopen
            # once and retry without corrupting the metadata-derived frame
            # count; otherwise later valid frames become unreachable.
            self.cap.release()
            self.cap = cv2.VideoCapture(self.video_path)
            if not self.cap.isOpened():
                return None
            self._seek(index)
            frame = self._read_next()
        return frame

    def get_frame_copy(self, index: int) -> Optional[np.ndarray]:
        frame = self.get_frame(index)
        if frame is None:
            return None
        return frame.copy()

    def release(self) -> None:
        if self.cap is not None and self.cap.isOpened():
            self.cap.release()


def iter_frames(
    video_path: str, start: int, stop: int, step: int = 1, extra: Iterable[int] = ()
) -> Iterator[Tuple[int, np.ndarray]]:
    """Decode frames ``start..stop`` (inclusive) in order with their own capture.

    Yields every ``step``-th frame plus any index listed in ``extra``.

    Frames between samples are grabbed without conversion, which is far faster
    than seeking to each sample. Safe to use from a background thread.
    """

    cap = cv2.VideoCapture(video_path)
    try:
        if not cap.isOpened():
            return
        start = max(0, int(start))
        step = max(1, int(step))
        wanted = {int(i) for i in extra}
        cap.set(cv2.CAP_PROP_POS_FRAMES, start)
        index = start
        while index <= stop:
            if (index - start) % step == 0 or index in wanted:
                ok, frame = cap.read()
                if not ok:
                    return
                yield index, frame
            elif not cap.grab():
                return
            index += 1
    finally:
        cap.release()
