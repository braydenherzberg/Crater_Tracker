#!/usr/bin/env bash
# Build dist/Crater.app and Crater-macOS.dmg (same recipe as CI).
set -euo pipefail
cd "$(dirname "$0")/.."
# Avoids the Xcode licence prompt when only the Command Line Tools are needed.
if [ -d /Library/Developer/CommandLineTools ]; then export DEVELOPER_DIR=/Library/Developer/CommandLineTools; fi
python3 -m pip install -e ".[dev]"
pyinstaller --noconfirm packaging/crater.spec
rm -rf build/dmg && mkdir -p build/dmg
cp -R dist/Crater.app build/dmg/ && ln -s /Applications build/dmg/Applications
hdiutil create -volname Crater -srcfolder build/dmg -ov -format UDZO dist/Crater-macOS.dmg
echo "Built dist/Crater.app and dist/Crater-macOS.dmg"
