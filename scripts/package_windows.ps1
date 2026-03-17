Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

python -m pip install --upgrade pip
python -m pip install ".[dev]"

pyinstaller `
  --name CraterAnalysis `
  --windowed `
  --noconfirm `
  run_desktop.py

Write-Host "Build complete. Output in dist/CraterAnalysis/"
Write-Host "Wrap with Inno Setup or MSIX for signed installer distribution."

