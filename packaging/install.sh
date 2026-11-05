#!/usr/bin/env bash
# Run by the admin: sudo packaging/install.sh --no-claude | sudo packaging/install.sh <managed-settings.json>
# Decision rows 18, 26, 34. Never runs gov-aios, never creates anything in the data home.
# Root writes nothing under the user's home except the guarded chown of root-owned data-home files.
set -euo pipefail
cd "$(dirname "$0")/.."

SIGNER_CN="GOV-AIOS Dev" # must match GOVAIOS_SIGN_ID used by build.sh

[ "$(id -u)" -eq 0 ] && [ -n "${SUDO_USER:-}" ] || { echo "run with sudo, as a normal user: sudo packaging/install.sh ..." >&2; exit 1; }
[ "$SUDO_USER" != root ] || { echo "SUDO_USER is root" >&2; exit 1; }

SETTINGS=""
case "${1:-}" in
  --no-claude) [ $# -eq 1 ] || { echo "usage: install.sh --no-claude | install.sh <managed-settings.json>" >&2; exit 2; } ;;
  ""|-*) echo "usage: install.sh --no-claude | install.sh <managed-settings.json>" >&2; exit 2 ;;
  *) [ $# -eq 1 ] && [ -f "$1" ] || { echo "settings file not found: $1" >&2; exit 2; }; SETTINGS="$1" ;;
esac

APP_SRC="dist/gov-aios.app"
APP=/Applications/gov-aios.app
APP_NEW=/Applications/gov-aios.app.new
REQ="identifier \"com.govaios.cli\" and certificate leaf[subject.CN] = \"$SIGNER_CN\""
[ -d "$APP_SRC" ] || { echo "missing $APP_SRC: run packaging/build.sh first" >&2; exit 1; }
codesign --verify --strict "$APP_SRC" || { echo "$APP_SRC fails codesign --verify --strict" >&2; exit 1; }

# Under sudo $HOME is root's: take the user's home and uid from the directory service.
UHOME=$(/usr/bin/dscl . -read "/Users/$SUDO_USER" NFSHomeDirectory | /usr/bin/sed 's/^NFSHomeDirectory: *//')
UID_N=$(id -u "$SUDO_USER")
[ "$UID_N" -ne 0 ] || { echo "refusing: $SUDO_USER has uid 0" >&2; exit 1; }
[ -n "$UHOME" ] && [ -d "$UHOME" ] || { echo "cannot resolve home of $SUDO_USER" >&2; exit 1; }
DATA="$UHOME/Library/Application Support/GOV-AIOS"
AGENTS="$UHOME/Library/LaunchAgents"
PLIST="$AGENTS/com.govaios.guard.plist"
MS_DIR="/Library/Application Support/ClaudeCode"
MS_TMP="$MS_DIR/.managed-settings.json.$$"
trap 'rm -rf "$APP_NEW" "$MS_TMP"' EXIT

# Stop the old guard before replacing the app under it (errors ignored: it may not be loaded).
launchctl bootout "gui/$UID_N/com.govaios.guard" 2>/dev/null || true

# Stage the new app root-owned, verify the root-owned copy against the pinned signer, then swap.
rm -rf "$APP_NEW"
/usr/bin/ditto "$APP_SRC" "$APP_NEW"
chown -R root:wheel "$APP_NEW"
codesign --verify --strict "-R=$REQ" "$APP_NEW" || { echo "installed copy fails signer check ($SIGNER_CN)" >&2; exit 1; }
rm -rf "$APP"
mv "$APP_NEW" "$APP"

if [ -n "$SETTINGS" ]; then
  mkdir -p "$MS_DIR"
  cp "$SETTINGS" "$MS_TMP"
  chown root:wheel "$MS_TMP"; chmod 0644 "$MS_TMP"
  # A truncated or wrong settings file would lock Claude Code out: validate the root-owned copy.
  /usr/bin/python3 -m json.tool "$MS_TMP" >/dev/null || { echo "settings are not valid JSON" >&2; exit 1; }
  /usr/bin/python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); sys.exit(0 if isinstance(d,dict) and "hooks" in d else 1)' "$MS_TMP" \
    || { echo "settings must be a JSON object with \"hooks\"" >&2; exit 1; }
  mv -f "$MS_TMP" "$MS_DIR/managed-settings.json"
elif [ -e "$MS_DIR/managed-settings.json" ]; then
  echo "note: --no-claude keeps the existing managed settings"
fi

# The plist is written as the user, so root never writes through user-owned paths.
sudo -u "$SUDO_USER" /bin/mkdir -p "$AGENTS"
sudo -u "$SUDO_USER" /usr/bin/install -m 0644 packaging/com.govaios.guard.plist "$PLIST"

# Hand back root-owned data-home files only (not chown -R: it would touch the UF_APPEND audit log).
# Refuse symlinked components; skip hard-linked files (a link could point at a system file).
if [ -e "$DATA" ] || [ -L "$DATA" ]; then
  for p in "$UHOME/Library" "$UHOME/Library/Application Support" "$DATA"; do
    [ ! -L "$p" ] || { echo "refusing: $p is a symlink" >&2; exit 1; }
  done
  find -P "$DATA" -xdev -user 0 \( -type d -o \( -type f -links 1 \) \) -exec chown -h "$SUDO_USER" {} +
  [ -z "$(find -P "$DATA" -xdev -user 0 -print -quit)" ] || { echo "root-owned files remain in $DATA; fix by hand" >&2; exit 1; }
fi

cat <<MSG
Installed $APP${SETTINGS:+ and managed settings}.
Now, in System Settings > Privacy & Security, add $APP to:
  - Accessibility
  - Screen Recording
(this script changes no TCC setting). Then run: bin/gov-aios doctor
MSG

for i in 1 2 3; do
  launchctl bootstrap "gui/$UID_N" "$PLIST" && exit 0
  [ "$i" -eq 3 ] || sleep 1
done
echo "bootstrap failed; run: launchctl bootstrap gui/$UID_N \"$PLIST\"" >&2
exit 1
