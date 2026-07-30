from __future__ import annotations

from collections import OrderedDict
from typing import Optional

import cv2
import numpy as np


class VideoReader:
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
        self._frames = None
        self._cache: "OrderedDict[int, np.ndarray]" = OrderedDict()

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

    def get_frame(self, index: int) -> Optional[np.ndarray]:
        if index < 0 or index >= self.frame_count:
            return None

        if self._frames is not None:
            return self._frames[index]

        if index in self._cache:
            self._cache.move_to_end(index)
            return self._cache[index]

        self.cap.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, frame = self.cap.read()
        if not ok:
            # Random access can fail transiently on inter-frame codecs. Reopen
            # once and retry without corrupting the metadata-derived frame
            # count; otherwise later valid frames become unreachable.
            self.cap.release()
            self.cap = cv2.VideoCapture(self.video_path)
            if not self.cap.isOpened():
                return None
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, index)
            ok, frame = self.cap.read()
            if not ok:
                return None

        self._cache[index] = frame
        if len(self._cache) > self.max_cache_size:
            self._cache.popitem(last=False)
        return frame

    def get_frame_copy(self, index: int) -> Optional[np.ndarray]:
        frame = self.get_frame(index)
        if frame is None:
            return None
        return frame.copy()

    def release(self) -> None:
        if self.cap is not None and self.cap.isOpened():
            self.cap.release()
