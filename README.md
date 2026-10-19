# Crater

Operator-guided crater tracing for side-camera videos, including plume–surface
experiments. You draw the
crater line on a few frames; Crater snaps it to the image edge with sub-pixel
precision, tracks it between your keyframes, shows you where tracking is weak,
and exports calibrated width, depth and area for every frame.

Everything runs offline. Videos never leave your computer.

## Download

Get the latest build from the
[Releases page](https://github.com/braydenherzberg/Crater_Tracker/releases/latest):

| System | File |
| --- | --- |
| Mac with Apple silicon (M1 or newer) | `Crater-macOS-AppleSilicon.dmg` |
| Intel Mac | `Crater-macOS-Intel.dmg` |
| Windows 10 / 11 | `Crater-Windows-Setup.exe` (or the portable `Crater-Windows.zip`) |

**macOS:** open the DMG and drag Crater into Applications. The first launch is
blocked because the app is not yet notarized: open **System Settings → Privacy
& Security** and click **Open Anyway**.
**Windows:** if SmartScreen appears, click **More info → Run anyway**.

## First launch and tutorial

Click **Built-in tutorial** on the welcome screen (or **Tutorial** in the
header, **Help → Built-in Tutorial**, F1). The seven-step walkthrough works
without an internet connection and its buttons operate the real app. **Open
practice video** loads a bundled synthetic clip, with a labelled 10 mm span
and 64 mm full-image width, so you can practise calibration, tracing, saving
and exporting before opening experiment footage. The clip illustrates the
workflow; it is not experimental validation.

**Help → Offline Help and Shortcuts** includes the workflow, controls and
measurement limits. The online measurement-method link is optional.

## Original threshold workflow

**Tools → Original Threshold Tuner…** opens the current frame beside its
threshold mask, with threshold, smoothing, despeckle, independent left/right
zones, surface boundary, scan direction, channel and image tilt. After checking
the candidate, choose **Use reviewed profile as keyframe** and refine it in
the main canvas. Tilted candidates are mapped back to original image coordinates.
This retains the original tuning workflow while using the current measurement
and export system. The main workflow uses operator-defined guides rather than
unattended threshold detection.

Older sessions with `starred_frames` retain those records. **Tools → Review
Original Saved Profile…** selects a saved frame and reopens its settings in the
tuner for review. Original saved profiles are not silently accepted as new
measurements; confirm the scale and review the interface first. The current
baseline/rim method may produce different values from the original fixed-floor
method.

## Workflow

1. **Open a video** (⌘O / Ctrl+O). A saved session for the same video opens
   with it automatically.
2. **Find event.** Crater scans the whole run (about 15 s for a 10,000-frame
   video), marks the experiment on the timeline and jumps to where the scene
   settles.
3. **Set the scale.** Enter the real width of the full frame and click **Use width**, or press **K** and
   click two points a known distance apart (more accurate: measure in the
   crater's plane). Until scale is confirmed, measurements use pixels and
   calibrated export is disabled.
4. **Trace a keyframe.** Press **D** and click along the crater interface from
   flat ground on the left to flat ground on the right. A 5× loupe follows the
   cursor. Drag a point to move it, right-click to delete it.
5. **Add keyframes where needed.** Step through the run (←/→, ⇧←/→). On any
   frame, **D** starts from the interpolated line, so you only nudge a few
   points; **S** keeps an interpolated line that is already right. After every
   edit Crater tracks the whole keyframe range in the background and marks
   weak frames in amber on the timeline: press **N** to jump to the next one.
6. **Export** (⌘E / Ctrl+E) a CSV with one row per sampled frame, plus an
   optional profile-point CSV and a JSON file recording how the numbers were
   made.

A single keyframe exports that frame only. Two or more keyframes define the
interval for a time series. Contrast and temporal median affect the display
only; measurement and export use the original frame. Snap is saved per session
and applies to both desktop and command-line export.

Save with ⌘S / Ctrl+S. Sessions live in `~/.crater_analysis/sessions/`.

## What you see

- **Amber points and line:** your clicks. Solid on keyframes, dashed on an
  unsaved line, dotted where the line is interpolated.
- **White line:** the tracked interface after edge snapping.
- **Dashed white line and ticks:** the rim-to-rim baseline and the rims.
- **Section view** (under the video): the tracked profile with the depth axis
  stretched so millimetre-scale craters are visible, with dimension lines.
- **Timeline:** the whole run on top and a zoomable window below (scroll to
  zoom), with scene activity, the event, keyframes, per-frame edge support
  (amber = weak) and the width through time.

## Keys

| Key | Action | Key | Action |
| --- | --- | --- | --- |
| D | Edit line on this frame | ← / → | Previous / next frame |
| S | Keep line as keyframe | ⇧← / ⇧→ | Back / forward 24 frames |
| X | Clear this frame | [ / ] | Previous / next keyframe |
| ⌘Z / ⌫ | Undo (⇧⌘Z redo) | N | Next weak frame |
| E | Snap to edge on/off | Space | Play / pause |
| C | Enhance contrast (display only) | Wheel | Zoom video · Alt-drag pans · F fits |
| T | 7-sample temporal median (display only) | K | Measure scale |
| P | Save frame with overlays as PNG | Esc | Stop editing |

## Measurements

Each exported row has `frame, time_s, source, frames_to_key, width_mm,
depth_mm, area_mm2, baseline_tilt_deg, left_rim_x_mm, right_rim_x_mm,
deepest_x_mm, edge_support, confidence, notes`.

- `source` is `keyframe` (your line) or `interpolated` / `held` (derived).
- `edge_support` is the share of the line with a clear brightness change
  across it. Below 30% the image barely shows the interface.
- `confidence` combines distance from the nearest keyframe with edge support.
  It is a quality indicator, not an uncertainty interval.

The method, its limits and validation advice are in
[`docs/analysis_method.md`](docs/analysis_method.md).

## Command line

```bash
# Export a time series from a saved session
python -m crater_app.cli_batch --session ~/.crater_analysis/sessions/gt_MP_Run3.json \
  --out mp3_series.csv --frame-step 10 --profiles

# Score tracking against hand-labelled gt_* sessions (see docs/benchmark.md)
python -m crater_app.cli_benchmark run
```

## Run from source

Python 3.10 or newer:

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
python -m pip install -e ".[dev]"
python run_desktop.py [video.mp4]
pytest -q
```

## Building and releasing

`scripts/package_macos.sh` and `scripts/package_windows.ps1` build locally with
the same recipe as CI (`packaging/crater.spec`). Pushing a tag such as `v0.5.0`
makes GitHub Actions test the code, build and smoke-test the Mac and Windows
apps, and publish them on the Releases page. See
[`docs/release.md`](docs/release.md).
