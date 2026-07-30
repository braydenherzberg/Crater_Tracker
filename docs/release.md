# Desktop release guide

## Local builds

Create a clean virtual environment, then run:

### macOS

```bash
bash scripts/package_macos.sh
```

Expected output: `dist/CraterAnalysis.app`.

### Windows

```powershell
powershell -ExecutionPolicy Bypass -File scripts/package_windows.ps1
```

Expected output: `dist/CraterAnalysis/CraterAnalysis.exe`.

## GitHub Actions

`.github/workflows/build-desktop.yml` runs tests and builds on macOS and
Windows. Manual runs upload downloadable workflow artifacts. A `v*` tag also
creates a draft GitHub Release with platform archives.

These builds are unsigned until signing credentials are configured.

## Signing requirements

### macOS

For a normal double-click installation without a Gatekeeper override:

1. Sign the application with a Developer ID Application certificate.
2. Submit it to Apple notarization.
3. Staple the notarization ticket.
4. Package the signed application as a DMG or ZIP.

### Windows

For reduced SmartScreen warnings:

1. Sign the executable and installer with an Authenticode certificate.
2. Package with MSIX or a maintained installer builder.
3. Sign the final installer.

Signing identities, secrets, and legal publisher names are owner-controlled
release inputs and must not be committed.

## Release verification

Test each produced package on a clean supported machine:

- Launch by double-clicking; no Python installation is present.
- Open MP4 and MOV samples.
- Scrub, play, and run Auto Find Crater.
- Confirm overlay alignment and units.
- Save/load a preset and session.
- Export snapshot, profile CSV, and metrics CSV.
- Reopen exported files in standard applications.
- Verify app version and archive checksum.

Before making the repository public, the owner must select and add an
appropriate open-source license.

