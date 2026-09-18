# Releasing

## Publish a release

1. Update `version` in `pyproject.toml` and `__version__` in
   `crater_app/__init__.py`, and add a CHANGELOG entry.
2. Commit, then tag and push:

   ```bash
   git tag v0.5.0
   git push origin main v0.5.0
   ```

3. GitHub Actions (`.github/workflows/build-desktop.yml`) runs the tests, builds
   the apps, launches each built app against a generated test video
   (`--smoke-test`), and publishes a GitHub Release with:
   `Crater-macOS-AppleSilicon.dmg`, `Crater-macOS-Intel.dmg`,
   `Crater-Windows-Setup.exe` and `Crater-Windows.zip`.

Pushes to `main` and pull requests run the same builds and attach the files to
the workflow run (Actions tab → run → Artifacts) without publishing a release.

## Local builds

```bash
bash scripts/package_macos.sh                                      # dist/Crater.app, dist/Crater-macOS.dmg
powershell -ExecutionPolicy Bypass -File scripts/package_windows.ps1  # dist\Crater\Crater.exe
```

`python packaging/make_icons.py` regenerates the icons.

## Signing (optional, removes first-launch warnings)

The builds are unsigned (macOS: ad-hoc signed), so macOS asks users to
approve the first launch under Privacy & Security and Windows SmartScreen may
warn. To remove that:

- **macOS:** sign with a Developer ID Application certificate, notarize with
  `notarytool`, staple the ticket, then build the DMG. Requires an Apple
  Developer Program membership.
- **Windows:** sign `Crater.exe` and the installer with an Authenticode
  certificate.

Store certificates as GitHub Actions secrets; never commit them.

## Before making the repository public

Choose and add a licence.
