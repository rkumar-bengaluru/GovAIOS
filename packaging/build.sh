#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
.venv/bin/pyinstaller --clean --noconfirm packaging/gov-aios.spec
codesign --force --deep --options runtime --entitlements packaging/entitlements.plist --sign "${GOVAIOS_SIGN_ID:--}" --identifier com.govaios.cli dist/gov-aios.app
codesign --verify --strict --verbose=2 dist/gov-aios.app
