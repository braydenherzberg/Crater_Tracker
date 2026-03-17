# Release and Packaging Guide

## 1) Prepare environment

- macOS:
  - `python3 -m pip install .[dev]`
- Windows:
  - `python -m pip install .[dev]`

## 2) Build desktop binaries

- macOS:
  - `bash scripts/package_macos.sh`
- Windows:
  - `powershell -ExecutionPolicy Bypass -File scripts/package_windows.ps1`

## 3) Sign installers

- macOS:
  - Sign `dist/CraterAnalysis.app` with Apple Developer certificate.
  - Notarize app and staple ticket.
  - Package as `.dmg`.
- Windows:
  - Sign executable and installer with Authenticode certificate.
  - Use Inno Setup or MSIX to create installer.

## 4) Publish

- Upload artifacts to GitHub Releases.
- Attach checksums.
- Include `README.md` install and usage notes.

## 5) Verification checklist

- App starts on a clean machine.
- User can open local videos and run analysis.
- Snapshot export works.
- Visited-frame CSV and full-video CSV exports work.
- Preset save/load works.

