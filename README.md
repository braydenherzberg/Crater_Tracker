# Crater

Operator-guided crater tracing for side-camera impact videos. You draw the
crater line on a few frames; Crater snaps it to the image edge with sub-pixel
precision, tracks it between your keyframes, shows you where tracking is weak,
and exports calibrated width, depth and area for every frame.

Everything runs offline. Videos never leave your computer.

## Download

Get the latest build from the
[Releases page](https://github.com/braydenherzberg/crater_tracker/releases/latest):

| System | File |
| --- | --- |
| Mac with Apple silicon (M1 or newer) | `Crater-macOS-AppleSilicon.dmg` |
| Intel Mac | `Crater-macOS-Intel.dmg` |
| Windows 10 / 11 | `Crater-Windows-Setup.exe` (or the portable `Crater-Windows.zip`) |

**macOS:** open the DMG and drag Crater into Applications. The first launch is
blocked because the app is not yet notarized: open **System Settings → Privacy
& Security** and click **Open Anyway**.
**Windows:** if SmartScreen appears, click **More info → Run anyway**.

## Workflow

1. **Open a video** (⌘O / Ctrl+O). A saved session for the same video opens
   with it automatically.
2. **Find event.** Crater scans the whole run (about 15 s for a 10,000-frame
   video), marks the experiment on the timeline and jumps to where the scene
   settles.
3. **Set the scale.** Enter the real width of the full frame, or press **K** and
   click two points a known distance apart (more accurate: measure in the
   crater's plane).
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
| T | 7-frame temporal median (removes moving dust) | K | Measure scale |
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
