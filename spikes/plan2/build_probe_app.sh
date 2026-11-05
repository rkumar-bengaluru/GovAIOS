#!/usr/bin/env bash
# Builds build/probe/dist/gov-aios-probe.app (bundle id com.govaios.probe) running probe_sandbox.py,
# PyInstaller --onedir and signed like packaging/build.sh, so TCC treats it as it will treat gov-aios.
set -euo pipefail
cd "$(dirname "$0")/../.."
OUT=build/probe
.venv/bin/pyinstaller --clean --noconfirm --onedir --windowed --name gov-aios-probe \
  --osx-bundle-identifier com.govaios.probe \
  --distpath "$OUT/dist" --workpath "$OUT/work" --specpath "$OUT" \
  --hidden-import AppKit --hidden-import ApplicationServices --hidden-import Quartz \
  --hidden-import LocalAuthentication \
  spikes/plan2/probe_sandbox.py
APP="$OUT/dist/gov-aios-probe.app"
plutil -replace LSUIElement -bool true "$APP/Contents/Info.plist"
codesign --force --deep --options runtime --entitlements packaging/entitlements.plist \
  --sign "${GOVAIOS_SIGN_ID:-GOV-AIOS Dev}" --identifier com.govaios.probe "$APP"
codesign --verify --strict --verbose=2 "$APP"
echo "built $APP"
