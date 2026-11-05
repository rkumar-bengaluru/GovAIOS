#!/usr/bin/env bash
# Run by the admin: sudo packaging/install.sh --no-claude | sudo packaging/install.sh <managed-settings.json>
# Decision rows 18, 26, 34. Never runs gov-aios, never creates anything in the data home.
set -euo pipefail
cd "$(dirname "$0")/.."

[ "$(id -u)" -eq 0 ] && [ -n "${SUDO_USER:-}" ] || { echo "run with sudo, as a normal user: sudo packaging/install.sh ..." >&2; exit 1; }
[ "$SUDO_USER" != root ] || { echo "SUDO_USER is root" >&2; exit 1; }

SETTINGS=""
case "${1:-}" in
  --no-claude) [ $# -eq 1 ] || { echo "usage: install.sh --no-claude | install.sh <managed-settings.json>" >&2; exit 2; } ;;
  ""|-*) echo "usage: install.sh --no-claude | install.sh <managed-settings.json>" >&2; exit 2 ;;
  *) [ $# -eq 1 ] && [ -f "$1" ] || { echo "settings file not found: $1" >&2; exit 2; }; SETTINGS="$1" ;;
esac

# A truncated settings file would lock Claude Code out: validate before touching anything.
if [ -n "$SETTINGS" ]; then
  /usr/bin/plutil -lint "$SETTINGS" >/dev/null || { echo "settings file is not valid JSON: $SETTINGS" >&2; exit 1; }
  /usr/bin/python3 -m json.tool "$SETTINGS" >/dev/null || { echo "settings file is not valid JSON: $SETTINGS" >&2; exit 1; }
fi

APP_SRC="dist/gov-aios.app"
APP=/Applications/gov-aios.app
[ -d "$APP_SRC" ] || { echo "missing $APP_SRC: run packaging/build.sh first" >&2; exit 1; }
codesign --verify --strict "$APP_SRC" || { echo "$APP_SRC fails codesign --verify --strict" >&2; exit 1; }

# Under sudo $HOME is root's: take the user's home and uid from the directory service.
UHOME=$(/usr/bin/dscl . -read "/Users/$SUDO_USER" NFSHomeDirectory | /usr/bin/awk '{print $2}')
UID_N=$(id -u "$SUDO_USER")
[ -n "$UHOME" ] && [ -d "$UHOME" ] || { echo "cannot resolve home of $SUDO_USER" >&2; exit 1; }
DATA="$UHOME/Library/Application Support/GOV-AIOS"
AGENTS="$UHOME/Library/LaunchAgents"
PLIST="$AGENTS/com.govaios.guard.plist"
MS_DIR="/Library/Application Support/ClaudeCode"

# Stop the old guard before replacing the app under it (errors ignored: it may not be loaded).
launchctl bootout "gui/$UID_N/com.govaios.guard" 2>/dev/null || true

rm -rf "$APP"
/usr/bin/ditto "$APP_SRC" "$APP"
chown -R root:wheel "$APP"

if [ -n "$SETTINGS" ]; then
  mkdir -p "$MS_DIR"
  install -o root -g wheel -m 0644 "$SETTINGS" "$MS_DIR/managed-settings.json"
fi

# Plist already names /Applications/gov-aios.app/Contents/MacOS/gov-aios guard.
install -d -o "$SUDO_USER" -m 0755 "$AGENTS"
install -o root -g wheel -m 0644 packaging/com.govaios.guard.plist "$PLIST"
/usr/bin/plutil -lint "$PLIST" >/dev/null

# Hand back root-owned files only (not chown -R: it would needlessly touch the UF_APPEND audit log).
if [ -d "$DATA" ]; then
  find "$DATA" -user 0 -exec chown -h "$SUDO_USER" {} +
  if find "$DATA" -user 0 | grep -q .; then echo "root-owned files remain in $DATA" >&2; exit 1; fi
fi

launchctl bootstrap "gui/$UID_N" "$PLIST"

cat <<MSG
Installed $APP${SETTINGS:+ and managed settings}.
Now, in System Settings > Privacy & Security, add $APP to:
  - Accessibility
  - Screen Recording
(this script changes no TCC setting). Then run: bin/gov-aios doctor
MSG
