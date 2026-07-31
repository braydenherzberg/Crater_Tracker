# Guided side-profile analysis

## Why the operator defines the interface

Low-visibility side-camera footage can contain several plausible boundaries:
container walls, material/air transitions, dust fronts, reflections, and the
physical crater interface. Image strength alone cannot establish which one is
the experimental target. The supplied runs demonstrated that the previous
automatic surface detector could trace a clear boundary that was not the crater.

Guided tracking is therefore the default. The software reports no crater
measurement until the operator identifies the intended physical interface.

## Guided measurement model

1. Scrub to a frame where the crater boundary can be identified.
2. Click points left-to-right along the physical subsurface interface, including
   a short level supporting section before and after the crater.
3. Save the line as a guide keyframe.
4. Add keyframes later in the video whenever the interpolated line no longer
   follows the same interface.
5. Review each measurement before accepting it for export.

Sparse clicks are linearly interpolated in image space to produce a dense
profile. Between guide keyframes, the curves are resampled and interpolated in
time. Before the first keyframe and after the last, the nearest guide is held;
these extrapolated regions require particularly careful review.

When **Track nearby edge** is enabled, the interpolated curve is refined using
vertical image-gradient evidence. Refinement is limited to 14 pixels around the
guide and carries a strong distance penalty. This local step may improve fit in
low contrast, but it cannot legitimately identify a different interface.

The outer portions of the curve estimate the undisturbed local level. The rims
are where the curve leaves and returns to that level; the first and last clicks
are not assumed to be rims. Pixel coordinates increase downward, so depth is
the positive vertical distance below the inferred rim baseline. Measurements are:

- **Rim-to-rim width:** horizontal distance between inferred shoulder transitions
- **Maximum depth:** largest vertical distance below the local rim baseline
- **Cross-section area:** numerical integral of positive depth along the profile
- **Baseline tilt:** angle of the local rim baseline in image coordinates
- **Local edge support:** strength of nearby image-gradient evidence, not proof
  that the selected interface is physically correct

Pixels are converted to millimeters using the operator-entered physical width
of the full source frame.

## Event-aware review-frame selection

**Analyze run** samples the recording, estimates the first major experiment
transition, and proposes a stable post-event review frame. This is a navigation
aid. It does not define the crater interface; the operator must still draw and
save a guide line.

The proposed review image uses a seven-frame temporal median to reduce moving
dust and transient glare. Measurements remain two-dimensional image-plane
measurements.

## Legacy automatic detector

When guided tracking is disabled, the legacy detector searches for a sustained
bright-to-dark vertical transition, smooths it, and finds basin-like excursions.
This remains useful for synthetic tests and some high-contrast material surfaces,
but it is not a validated crater detector for the supplied low-visibility runs.
Its confidence score is a shape/evidence heuristic, not a scientific uncertainty
interval and not proof that the traced boundary is the crater.

## Important limitations

- A guide is a human annotation, not independent ground truth.
- Interpolated frames can be wrong when the interface changes between keyframes.
- Calibration assumes one horizontal millimeter-per-pixel scale across the frame.
- Refraction and lens distortion through transparent walls are not corrected.
- Depth is vertical in image coordinates, not normal to a tilted baseline.
- A partially cropped crater may not contain both physical rims.
- Cross-section area is not crater volume.

## Recommended validation

Before reporting scientific measurements:

1. Define the physical crater interface in experimental terms.
2. Have a second reviewer label a representative blinded frame set.
3. Compare guided/interpolated curves with those labels and retain the errors.
4. Record calibration in the same optical plane as the crater.
5. Measure repeatability across neighboring post-event frames.
6. Preserve the software version, source filename, frame index, guide keyframes,
   accepted overlay snapshots, and exported measurements.
