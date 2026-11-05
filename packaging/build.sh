#!/usr/bin/env bash
# Entitlement policy: decisions log row 10 (library validation off only for non-Developer-ID builds).
set -euo pipefail
cd "$(dirname "$0")/.."
SIGN_ID="${GOVAIOS_SIGN_ID:--}"
PLIST="${GOVAIOS_ENTITLEMENTS:-packaging/entitlements.plist}"

# Assertion 1: exactly one key, disable-library-validation.
keys=$(plutil -convert json -o - "$PLIST" | python3 -c 'import json,sys; print(" ".join(sorted(json.load(sys.stdin))))')
[ "$keys" = "com.apple.security.cs.disable-library-validation" ] || { echo "ERROR: unexpected entitlements: $keys" >&2; exit 1; }

.venv/bin/pyinstaller --clean --noconfirm packaging/gov-aios.spec
ent=()
case "$SIGN_ID" in
  "Developer ID Application:"*) ;;
  *) ent=(--entitlements "$PLIST") ;;
esac
codesign --force --deep --options runtime ${ent[@]+"${ent[@]}"} --sign "$SIGN_ID" --identifier com.govaios.cli dist/gov-aios.app
codesign --verify --strict --verbose=2 dist/gov-aios.app

if [ ${#ent[@]} -eq 0 ]; then
  # Assertion 2: Developer ID build must not carry the entitlement.
  if codesign -d --entitlements - dist/gov-aios.app 2>&1 | grep -q disable-library-validation; then
    echo "ERROR: Developer ID build has disable-library-validation" >&2; exit 1
  fi
else
  echo "WARNING: library validation off (dev signing)" >&2
fi
