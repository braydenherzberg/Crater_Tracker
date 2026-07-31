# Crater Side-Profile Analyzer

An offline desktop application for tracing and measuring crater cross-sections
from side-camera experiment videos.

The analyzer is designed for bright-background/dark-material footage captured
through a transparent test container. It runs locally: videos and measurements
do not leave the computer.

## Current capabilities

- Operator-guided crater-line keyframes on the video canvas
- Spatial interpolation between sparse clicks and temporal interpolation between keyframes
- Conservative local edge refinement that cannot leave the user-defined search corridor
- Explicit no-measurement state until the physical crater interface is defined
- Rim-to-rim width, maximum depth, cross-section area, baseline tilt, and confidence
- Event-aware sampling of long recordings with post-event candidate selection
- Seven-frame temporal median review for low-visibility dust and glare
- Source-video FPS detection and calibrated millimeter exports
- Manual threshold/scan mode as a fallback for difficult footage
- Frame playback, scrubbing, overlays, bookmarks, presets, and saved sessions
- Snapshot, profile CSV, metrics CSV, and headless batch export
- macOS and Windows packaging scripts

The guided workflow draws:

- **Magenta:** the operator's clicked control points and line
- **Green/orange:** the dense tracked crater curve
- **Blue:** inferred shoulder-to-shoulder baseline and rim markers
- **Red:** deepest detected point

## Run from source

Python 3.10 or newer is required.

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
python -m pip install -e ".[dev]"
python run_desktop.py
```

## Recommended workflow

1. Open a side-camera video.
2. Enter the real width represented by the **full video frame**.
3. Leave **Use guided tracking** enabled.
4. Select **Analyze run** to locate the experiment event and review a stable
   post-event frame.
5. Select **Draw line on this frame** and click left-to-right along the true
   subsurface crater interface. Include a short level section on both sides so
   the software can locate where the crater leaves and returns to that baseline.
   Save the keyframe.
6. Scrub through the run. Add another keyframe wherever the interpolated line
   stops following the same physical interface.
7. Inspect the tracked curve and baseline, then accept frames for export.

Confidence is a quality heuristic, not a scientific uncertainty interval.
Measurements should not be accepted unless the overlay follows the physical
surface and the inferred rim-to-rim baseline is plausible.

The legacy automatic surface detector remains available when guided tracking is
disabled, but it is not a verified crater detector for the supplied low-visibility
runs. It can select a visually strong material/air boundary that is not the
intended physical crater. Do not treat its measurements as validated ground truth.

## Batch analysis

```bash
python -m crater_app.cli_batch \
  --video "/path/to/run.mp4" \
  --out "metrics.csv" \
  --frame-step 24
```

`--frame-step` is useful for high-speed footage. At 240 FPS, a step of 24
produces roughly ten measurement rows per second.

An optional JSON settings file may be supplied with `--settings-json`.

## Testing

```bash
pytest -q
```

The regression suite includes deterministic manual analysis, synthetic automatic
surface recovery, guided geometry, and interpolation between guide keyframes.

## Packaging

Local packaging instructions and release caveats are in
[`docs/release.md`](docs/release.md). GitHub Actions can build downloadable
macOS and Windows archives, but public frictionless distribution requires:

- Apple Developer ID signing and notarization for macOS
- Authenticode code signing for Windows
- A project license selected by the repository owner
- Clean-machine installation tests

## Analysis notes

The automatic method and its limitations are documented in
[`docs/analysis_method.md`](docs/analysis_method.md).
