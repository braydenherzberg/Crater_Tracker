#!/usr/bin/env bash
set -euo pipefail

python3 -m pip install --upgrade pip
python3 -m pip install ".[dev]"

pyinstaller \
  --name CraterAnalysis \
  --windowed \
  --clean \
  --noconfirm \
  run_desktop.py

echo "Build complete. Output in dist/CraterAnalysis.app"
echo "Create DMG with your preferred signing/notarization flow."
