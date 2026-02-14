# Crater Analysis App

Offline-first crater profile analysis for user-provided videos.

## What is included

- `crater_app/core`: deterministic analysis engine + settings + metrics
- `crater_app/desktop`: PySide6 desktop app with:
  - video open/play/scrub
  - grouped controls (threshold, smoothing, despeckle, tilt, bounds, surface)
  - overlays (guides/profile/mask panel toggles)
  - preset save/load
  - export snapshot, metrics CSV, and session JSON
- `crater_app/cli_batch.py`: headless batch CSV export
- `tests`: regression tests for deterministic output and expected metric ranges

## Local run

```bash
python3 -m pip install -r requirements.txt
python3 run_desktop.py
```

## Batch run

```bash
python3 -m crater_app.cli_batch --video "test3.mov" --out "metrics.csv"
```

Optional settings file:

```bash
python3 -m crater_app.cli_batch --video "test3.mov" --out "metrics.csv" --settings-json "preset.json"
```

## Packaging (Windows + macOS)

See `scripts/package_windows.ps1` and `scripts/package_macos.sh`.

## Web MVP

See `web_mvp/README.md` for an implementation scope and low-ops deployment options.

# crater_tracker
