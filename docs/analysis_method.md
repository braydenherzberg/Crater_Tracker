# Automatic side-profile analysis

## Measurement model

The application treats the visible material/air boundary as a two-dimensional
cross-section. Pixel coordinates increase downward, so a crater depression is
a positive vertical excursion in the traced surface.

The automatic pipeline:

1. Rotates the frame by the configured camera tilt.
2. Downscales to a bounded working width for predictable performance.
3. Searches for a sustained bright-to-dark vertical transition.
4. Uses a robust median guide, continuity penalty, and narrow-outlier rejection
   to suppress glare, wall markings, and isolated reflective edges.
5. Smooths and maps the trace back to source-frame pixels.
6. Uses a one-dimensional morphological surface model to identify basin-like
   downward excursions.
7. Refines the basin endpoints toward local rim candidates.
8. Measures depth and area against the straight line connecting those rims.
9. Converts pixels to millimeters from the user-entered full-frame width.

**Analyze run** adds a temporal stage:

1. Samples the full recording and estimates inter-frame motion near the surface.
2. Treats the first major transition as the experiment event rather than
   choosing a crater-like shape from a pre-event frame.
3. Ranks only post-event candidates using temporal change, persistence,
   surface visibility, geometry, and physical plausibility.
4. Re-analyzes the selected frame as a seven-frame temporal median to suppress
   moving dust and transient glare.

## Reported measurements

- **Rim-to-rim width:** horizontal distance between inferred rim points
- **Maximum depth:** largest perpendicular-in-image-y distance below the local baseline
- **Cross-section area:** numerical integral of positive depth across the crater
- **Baseline tilt:** angle of the inferred rim-to-rim line in image coordinates
- **Confidence:** heuristic combination of edge strength, trace continuity,
  basin prominence, edge clearance, width/depth plausibility, and baseline tilt

Confidence is explicitly capped by surface visibility. A clear-looking basin
cannot receive a strong rating when the underlying air/material boundary is
poorly supported.

The current depth measurement is vertical in the image, not normal to a tilted
baseline. Small residual camera tilt is reported so reviewers can decide
whether to correct the video or apply the tilt control.

## Important limitations

- Calibration assumes one horizontal millimeter-per-pixel scale across the frame.
- Refraction and lens distortion through transparent walls are not corrected.
- Occlusion, dust clouds, shadows, glare, and container edges can create false surfaces.
- Camera or container movement can look like a crater without temporal registration.
- A partially cropped crater may not contain both physical rims.
- Confidence is not a statistical confidence interval and does not establish accuracy.
- Cross-section area is not crater volume.

Use manual mode or reject the frame whenever the overlay does not visibly
follow the intended surface.

## Recommended validation

Before reporting scientific measurements:

1. Record a calibration target in the same optical plane as the surface.
2. Compare automatic traces with hand-labeled profiles on representative runs.
3. Measure repeatability across neighboring post-event frames.
4. Record accepted settings, software version, source filename, and frame index.
5. Preserve the overlay snapshot with exported measurements.
