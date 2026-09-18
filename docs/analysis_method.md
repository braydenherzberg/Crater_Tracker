# Measurement method

## Why the operator defines the interface

Low-visibility side-camera footage contains several plausible boundaries:
container walls, material/air transitions, dust fronts, reflections and the
physical crater interface. Image strength alone cannot establish which is the
experimental target; an earlier fully automatic detector traced clear
boundaries that were not the crater. Crater therefore measures only a line the
operator has placed on the intended interface, and uses the image only to
refine that line locally.

## From clicks to a measurement

1. **Guide.** Clicks are joined left to right into a line sampled every pixel.
   On a frame without its own keyframe the guide is interpolated in time
   between the neighbouring keyframes (each resampled over its own x-range and
   blended linearly). Before the first or after the last keyframe the nearest
   keyframe is *held*.
2. **Edge snap** (on by default, key E). Inside a ±14 px corridor around the
   guide a dynamic-programming path search chooses one row per column. It
   rewards vertical brightness change of the polarity that dominates along the
   guide (normally brighter above, darker below), penalises distance from the
   guide, and penalises slope changes relative to the guide. The image is
   blurred 8 px along x and 2 px along y first, because interfaces are close to
   horizontal. Rows are refined to sub-pixel precision and lightly smoothed
   (σ = 3 px). The snap cannot leave the corridor, so it cannot jump to a
   different interface.
3. **Baseline and rims.** The outer ~16% of the line on each side defines the
   undisturbed level (a straight-line fit). The rims are where the line leaves
   and returns to that level: the first crossing of 8% of the maximum depth,
   refined to the nearest return to the level. The first and last clicks are
   not assumed to be rims, so the line must extend onto flat ground on both
   sides; Crater warns when it does not, or when the two ends are not level.
4. **Metrics.** Depth is the vertical distance below the rim-to-rim baseline.
   Width is the horizontal rim-to-rim distance, area the integral of positive
   depth, and tilt the angle of the baseline in image coordinates. Pixels are
   converted with the session calibration.

## Quality indicators

- **Edge support** is the share of columns where the brightness changes by at
  least 3 grey levels across the snapped line (averaged 2–8 px either side).
  On the supplied footage a visible interface scores ~90%, featureless regions
  under 10%. Below 30% Crater shows a warning and the timeline marks the frame
  in amber.
- **Confidence** = 0.6 × temporal confidence + 0.4 × edge support. Temporal
  confidence is 1 on a keyframe and exp(−d / 240) for a frame d frames from the
  nearest keyframe (×0.7 when held beyond the last keyframe). It ranks frames
  for review; it is not an uncertainty interval.

## Measured repeatability

On Mars Perfect Run 3, frame 9,191, twelve simulated operators each placed 7
clicks with ±4 px of random error near the same line:

| | width, SD | depth, SD |
| --- | --- | --- |
| clicks only | 50.8 px (3.3 mm) | 4.8 px |
| with edge snap | 8.9 px (0.57 mm) | 2.0 px |

The snap makes the result far less dependent on how carefully the line was
clicked. Whether it lands on the *physically correct* interface still needs
hand-labelled ground truth: see [benchmark.md](benchmark.md).

## Finding the event

**Find event** decodes the run in order, keeps a grey thumbnail about every
N/600 frames and measures frame-to-frame change. The event is the strongest
sustained burst of change (the most activity within ~2 s), not the first
spike, because camera handling and lighting changes produce short spikes. The
suggested review frame is the first quiet stretch after the burst. It is a
navigation aid only.

## Limitations

- A keyframe is a human annotation, not independent ground truth.
- Interpolated frames can be wrong where the interface changes between
  keyframes; use the amber timeline marks and add keyframes there.
- Calibration assumes one scale across the frame. Refraction through
  transparent walls and lens distortion are not corrected; measuring the scale
  in the crater's plane (key K) reduces the error.
- Depth is vertical in image coordinates, not normal to a tilted baseline.
- A partially cropped crater may not contain both rims.
- Cross-section area is not crater volume.

## Before reporting results

1. Define the physical crater interface in experimental terms.
2. Label a representative frame set (`gt_*` sessions) and, ideally, have a
   second person label the same frames; run the benchmark.
3. Calibrate in the crater's optical plane.
4. Check repeatability on neighbouring post-event frames.
5. Keep the exported `_meta.json` with the data: it records the app version,
   video, calibration, keyframes and settings that produced the numbers.
