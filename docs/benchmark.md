# Tracking benchmark

The benchmark measures how closely guided tracking reproduces carefully labeled
crater lines. Run it before and after any tracking change. Keep a change only if
the numbers improve.

## 1. Label ground truth in the desktop app

Labels are ordinary saved sessions. No special tool is needed.

1. Open a run's **original `.MP4`** (full 1920×1080) and press **Find event**.
2. Turn **Snap** off (key **E**) while labelling, so what you see is exactly
   what you click.
3. Go to a post-event frame, press **D**, and click **carefully and densely**
   (about every 50–80 px, more on the walls) along the true subsurface crater
   interface. Use the loupe. Include a flat stretch of undisturbed material on
   both sides. Drag points to adjust; the frame becomes a keyframe once it has
   three points.
4. Repeat on **5–8 frames spread across the run** (for example every 1–2 s
   after the event). Include some hard frames, not only clean ones. Draw every
   label yourself: do not keep (S) an interpolated line as ground truth.
5. Save the session with a name starting with **`gt_`**, for example
   `gt_MP_Run3`. Use one session per video.

Tips:

- Label only what you would sign off on as the physical interface. Skip a frame
  if you can't tell where the interface is.
- The interpolation test needs **at least 3 labeled frames per video**.
- A second person labeling the same frames in their own `gt_…_reviewer2`
  session gives you a human-agreement reference. Don't mix both people's labels
  into one run.
- Labels live in `~/.crater_analysis/sessions/`, outside git. Back them up.

Events found by **Find event** on the supplied runs (239.76 FPS): Mars Perfect 3
≈ 8,806 (crater clear from ≈ 9,191), Mars Perfect 2 ≈ 18,093, Control 2
≈ 14,050, Control 1 ≈ 23,739. Label after the dust settles.

## 2. Check what's labeled

```bash
python3 -m crater_app.cli_benchmark status
```

## 3. Record a baseline

Run this once on unchanged code:

```bash
python3 -m crater_app.cli_benchmark run --save-baseline
```

## 4. Change the tracker, then re-run

```bash
python3 -m crater_app.cli_benchmark run
```

Each run prints a table and a comparison with the baseline, marking every metric
as better, same or WORSE. Per-frame details are written to
`local_analysis/benchmark/<timestamp>/cases.csv`, which is gitignored. When a
change is kept, re-save the baseline. Also re-save it whenever you add labels,
because comparisons are only fair on the same label set.

`--stabilize` scores against the app's 7-frame temporal-median image. `--clicks`
and `--noise-px` control how sloppy the simulated operator is.

## What is measured

For each labeled frame:

- **keyframe:** a simulated operator makes a few noisy clicks near your line
  (7 clicks, about 4 px of noise by default, fixed random seed). Guided
  analysis runs on those clicks and is compared with your careful line. This
  tests edge refinement and rim finding.
- **interpolation:** your label is hidden and rebuilt from the other labels in
  the same video, the same way the app interpolates between keyframes. This
  tests tracking between keyframes.

Each test runs with edge snapping off and on.

| Column | Meaning |
| --- | --- |
| curve | Mean vertical distance from your line (px) |
| p95 | 95th-percentile vertical distance (px), i.e. the worst stretches |
| width / depth | Error in rim-to-rim width and max depth, compared with the measurement taken from your own line |
| rims | Mean horizontal error of the two rim positions (px) |
| missed | Share of frames where your line gives a crater but the tracker gives none |

Rims are inferred from your line by the app's own rim rule. So "rims" measures
whether tracking reproduces your line well enough to land the rims in the same
place. It does not check whether that rim rule is physically correct. Judge that
by eye.

At the default 124 mm frame width, 1 px ≈ 0.065 mm.
