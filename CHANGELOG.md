# Changelog

## 0.5.0

Rebuilt desktop app around operator-guided tracing.

- New dark, single-accent interface: tool rail, video canvas, section view,
  two-level timeline and a focused inspector; legacy detection, threshold
  controls, presets and the mask panel are gone from the UI.
- Point editing on the canvas: click adds, drag moves, right-click deletes,
  a 5× loupe follows the cursor, wheel zoom and Alt-drag pan.
- Editing an interpolated frame starts from the interpolated line; **S** keeps
  an interpolated line as a keyframe. Full undo/redo.
- Background tracking pass after every edit marks weak frames on the timeline
  (N jumps to the next) and plots width through time.
- **Find event** scans the run and marks the strongest sustained burst of
  activity, then jumps to where the scene settles.
- Edge snap is now a dynamic-programming path search with polarity detection,
  anisotropic blur, sub-pixel rows and 1 px sampling. Across simulated
  operators it cuts width spread from 50.8 px to 8.9 px on Mars Perfect Run 3.
- Edge support now measures brightness contrast across the line; confidence
  decays with distance from the nearest keyframe.
- Warnings when the line does not reach flat ground or its ends are not level.
- Two-point scale calibration (K), stored in the session.
- Time-series export: one calibrated row per sampled frame between keyframes,
  optional profile points, and a provenance JSON. `cli_batch` now exports from
  a session.
- Sessions v2 (calibration, event scan) keep unknown keys from older sessions;
  opening a video reopens its latest session. Unsaved-changes prompt.
- Much faster scrubbing on HEVC footage: forward reads instead of seeks and
  backward block prefetch (backward step ~7 ms instead of ~150 ms).
- Tracking benchmark (`cli_benchmark`) scoring against `gt_*` sessions.
- Packaging: app icon, PyInstaller spec, macOS DMG (Apple silicon and Intel),
  Windows installer and zip, smoke-tested in CI and published on tagged
  releases.

## 0.4.0

- Added on-canvas crater-line annotation with left-to-right control points.
- Added saved guide keyframes and temporal curve interpolation between them.
- Added conservative local edge tracking constrained to 14 pixels around the guide.
- Made guided tracking the default and suppressed all crater metrics until an
  operator defines the intended physical interface.
- Defined guided rim points from the transitions away from the surrounding local level.
- Updated guided geometry from operator ground truth so level supporting wings
  locate the crater shoulders instead of being counted as crater width.
- Persisted guide keyframes in saved analysis sessions.
- Added regression tests for guided measurement and spatial/temporal interpolation.
- Reclassified the old automatic surface detector as unverified for the supplied
  low-visibility videos instead of presenting its output as a crater measurement.

## 0.3.0

- Replaced shape-only run selection with event-aware post-event ranking.
- Added seven-frame temporal median review for dust and transient glare.
- Added continuity-constrained surface tracing and reflective-spike rejection.
- Prevented container boundaries from serving as inferred crater rims.
- Capped geometry confidence by measured surface visibility.
- Disabled automatic measurement acceptance when evidence is weak.
- Rebuilt the desktop experience around a large review canvas and restrained
  inspector instead of a dense control dashboard.
- Added optional low-contrast enhancement for review without altering analysis pixels.
- Added regression coverage for hazy reflective footage and flat no-crater surfaces.

## 0.2.0

- Added automatic surface tracking, crater geometry, calibrated metrics,
  candidate search, batch fields, packaging automation, and analysis documentation.
