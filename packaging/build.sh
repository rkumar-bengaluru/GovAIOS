#!/usr/bin/env bash
# Entitlement policy: decisions log row 10 (library validation off only for non-Developer-ID builds).
set -euo pipefail
cd "$(dirname "$0")/.."
SIGN_ID="${GOVAIOS_SIGN_ID:--}"
PLIST="${GOVAIOS_ENTITLEMENTS:-packaging/entitlements.plist}"

# Assertion 1: exactly one key, disable-library-validation.
keys=$(plutil -convert json -o - "$PLIST" | python3 -c 'import json,sys; print(" ".join(sorted(json.load(sys.stdin))))')
[ "$keys" = "com.apple.security.cs.disable-library-validation" ] || { echo "ERROR: unexpected entitlements: $keys" >&2; exit 1; }

# Any failure from here on (build, signing, entitlement check) leaves no app behind to run by mistake.
trap 'rm -rf dist/gov-aios.app' ERR
.venv/bin/pyinstaller --clean --noconfirm packaging/gov-aios.spec
ent=()
case "$SIGN_ID" in
  "Developer ID Application:"*) ;;
  *) ent=(--entitlements "$PLIST") ;;
esac
codesign --force --deep --options runtime ${ent[@]+"${ent[@]}"} --sign "$SIGN_ID" --identifier com.govaios.cli dist/gov-aios.app
codesign --verify --strict --verbose=2 dist/gov-aios.app

# Backstop for any identity form (name, SHA-1, ...): a Developer ID signature must not carry the entitlement.
info=$(codesign -dvv dist/gov-aios.app 2>&1)
ents=$(codesign -d --entitlements - dist/gov-aios.app 2>&1)
check_dev_id() { # $1 = codesign -dvv output, $2 = entitlements output
  if [[ "$1" == *"Authority=Developer ID Application"* ]]; then
    if [[ "$2" == *disable-library-validation* ]]; then
      echo "ERROR: Developer ID build has disable-library-validation" >&2; return 1
    fi
  else
    echo "WARNING: library validation off (dev signing)" >&2
  fi
}
check_dev_id "$info" "$ents"
