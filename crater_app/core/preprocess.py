from __future__ import annotations

import cv2
import numpy as np


def rotate_frame(frame: np.ndarray, angle_deg: float) -> np.ndarray:
    if abs(angle_deg) < 1e-9:
        return frame
    h, w = frame.shape[:2]
    center = (w // 2, h // 2)
    rot_mtx = cv2.getRotationMatrix2D(center, angle_deg, 1.0)
    return cv2.warpAffine(
        frame,
        rot_mtx,
        (w, h),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REPLICATE,
    )


def select_channel(frame: np.ndarray, channel: int) -> np.ndarray:
    if channel == 0:
        return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    if channel == 1:
        return frame[:, :, 0]
    if channel == 2:
        return frame[:, :, 1]
    return frame[:, :, 2]


def build_solid_mask(gray: np.ndarray, threshold: int, clahe: cv2.CLAHE) -> np.ndarray:
    enhanced = clahe.apply(gray)
    blurred = cv2.GaussianBlur(enhanced, (15, 15), 0)
    _, thresh = cv2.threshold(blurred, threshold, 255, cv2.THRESH_BINARY_INV)
    solid_mask = np.zeros_like(thresh)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if contours:
        largest = max(contours, key=cv2.contourArea)
        cv2.drawContours(solid_mask, [largest], -1, (255), thickness=cv2.FILLED)
    return solid_mask

