from __future__ import annotations

from typing import List, Tuple

import numpy as np

from .settings import AnalysisSettings


def extract_profile_points(
    solid_mask: np.ndarray,
    settings: AnalysisSettings,
) -> List[Tuple[int, int]]:
    h, w = solid_mask.shape
    center_x = w // 2
    bracket_left = center_x - settings.zone_left
    bracket_right = center_x + settings.zone_right

    raw_x: List[int] = []
    raw_y: List[int] = []

    if settings.left_margin + settings.right_margin >= w:
        return []

    for x in range(settings.left_margin, w - settings.right_margin, settings.x_step):
        in_zone = bracket_left < x < bracket_right
        col = solid_mask[:, x]
        found_y = -1

        if settings.scan_mode == 1:
            col_rev = col[::-1]
            air = np.where(col_rev == 0)[0]
            if len(air) > 0:
                found_y = (h - 1) - int(air[0])
        else:
            sand = np.where(col == 255)[0]
            valid = sand[sand > settings.top_margin]
            if len(valid) > 0:
                found_y = int(valid[0])

        if found_y == -1:
            # Keep trace continuous across full span by falling back to the
            # surface boundary when a column has no detectable edge.
            found_y = settings.surface_boundary
        elif found_y >= (h - 5):
            found_y = settings.surface_boundary

        if not in_zone:
            # Outside crater zone, anchor trace to the surface baseline.
            found_y = settings.surface_boundary

        raw_x.append(x)
        raw_y.append(found_y)

    if not raw_x:
        return []

    if settings.despeckle > 1 and len(raw_y) > settings.despeckle:
        y_arr = np.array(raw_y)
        despeckled = y_arr.copy()
        k = settings.despeckle // 2
        for i in range(len(y_arr)):
            start = max(0, i - k)
            end = min(len(y_arr), i + k + 1)
            despeckled[i] = np.median(y_arr[start:end])
        raw_y = despeckled.tolist()

    if settings.smoothing <= 1:
        smoothed_y = np.array(raw_y, dtype=np.float64)
    else:
        # Edge-safe moving average (no endpoint trimming), so the trace reaches
        # the guide margins even with high smoothing values.
        y_arr = np.array(raw_y, dtype=np.float64)
        smoothed_y = np.zeros_like(y_arr)
        k = settings.smoothing // 2
        for i in range(len(y_arr)):
            start = max(0, i - k)
            end = min(len(y_arr), i + k + 1)
            smoothed_y[i] = float(np.mean(y_arr[start:end]))

    final_pts: List[Tuple[int, int]] = []
    for i, x in enumerate(raw_x):
        y_val = int(smoothed_y[i])
        if not (bracket_left < x < bracket_right):
            y_val = settings.surface_boundary
        final_pts.append((x, y_val))
    return final_pts

