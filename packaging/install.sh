#!/bin/bash
# Run by the admin: sudo packaging/install.sh --no-claude | sudo packaging/install.sh <managed-settings.json>
# Decision rows 18, 26, 34. Never runs gov-aios. The data home (0700) and the apps folder are created as the user.
# Root writes nothing under the user's home except the guarded chown of root-owned data-home files.
set -euo pipefail
export PATH=/usr/bin:/bin:/usr/sbin:/sbin
unset PYTHONPATH PYTHONHOME
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
REQ="identifier \"com.govaios.cli\" and certificate leaf[subject.CN] = \"$SIGNER_CN\""
[ -d "$APP_SRC" ] || { echo "missing $APP_SRC: run packaging/build.sh first" >&2; exit 1; }
codesign --verify --strict "$APP_SRC" || { echo "$APP_SRC fails codesign --verify --strict" >&2; exit 1; }

# Under sudo $HOME is root's: take the user's home and uid from the directory service.
UHOME=$(/usr/bin/python3 -I -c 'import pwd,sys;print(pwd.getpwnam(sys.argv[1]).pw_dir)' "$SUDO_USER")
UID_N=$(id -u "$SUDO_USER")
[ "$UID_N" -ne 0 ] || { echo "refusing: $SUDO_USER has uid 0" >&2; exit 1; }
[ -n "$UHOME" ] && [ -d "$UHOME" ] || { echo "cannot resolve home of $SUDO_USER" >&2; exit 1; }
DATA="$UHOME/Library/Application Support/GOV-AIOS"
AGENTS="$UHOME/Library/LaunchAgents"
PLIST="$AGENTS/com.govaios.guard.plist"
PANEL_PLIST="$AGENTS/com.govaios.panel.plist"
MS_DIR="/Library/Application Support/ClaudeCode"
MS_TMP="$MS_DIR/.managed-settings.json.$$"
STAGE=""
trap '[ -n "${STAGE:-}" ] && rm -rf "$STAGE"; rm -rf "$MS_TMP"' EXIT

# Stage in a private (0700, root) directory, verify the root-owned copy against the pinned signer, then swap.
STAGE=$(/usr/bin/mktemp -d /Applications/.gov-aios.XXXXXX)
/usr/bin/ditto "$APP_SRC" "$STAGE/gov-aios.app"
chown -R root:wheel "$STAGE/gov-aios.app"
chmod -R go-w "$STAGE/gov-aios.app"
codesign --verify --strict "-R=$REQ" "$STAGE/gov-aios.app" || { echo "installed copy fails signer check ($SIGNER_CN)" >&2; exit 1; }
# Hand back root-owned data-home files via fds (no path races, no symlinks, hard links fail closed).
# The helper is also the assertion: non-zero aborts the install.
/usr/bin/python3 -I packaging/handback.py "$UHOME" "$SUDO_USER" || { echo "data home hand-back failed; fix by hand, then re-run" >&2; exit 1; }

# Create the data home as the user at 0700 (an existing one is not loosened), then seed the apps folder as the user.
# Seeding never overwrites and lists files it left alone. Any failure here aborts before the old install is touched.
sudo -u "$SUDO_USER" /bin/bash -c 'umask 077; /bin/mkdir -p "$1"' _ "$DATA" || { echo "cannot create the data home" >&2; exit 1; }
sudo -u "$SUDO_USER" /bin/bash packaging/seed-apps.sh . "$DATA/apps" || { echo "seeding the apps folder failed" >&2; exit 1; }

# Settings are copied and validated before anything is stopped: a bad file must not leave a half-swapped install.
if [ -n "$SETTINGS" ]; then
  mkdir -p "$MS_DIR"
  cp "$SETTINGS" "$MS_TMP"
  chown root:wheel "$MS_TMP"; chmod 0644 "$MS_TMP"
  # A truncated or wrong settings file would lock Claude Code out: validate the root-owned copy.
  /usr/bin/python3 -I -m json.tool "$MS_TMP" >/dev/null || { echo "settings are not valid JSON" >&2; exit 1; }
  /usr/bin/python3 -I -c 'import json,sys; d=json.load(open(sys.argv[1])); sys.exit(0 if isinstance(d,dict) and "hooks" in d else 1)' "$MS_TMP" \
    || { echo "settings must be a JSON object with \"hooks\"" >&2; exit 1; }
fi

# Stop the old guard just before the swap (errors ignored: it may not be loaded).
launchctl bootout "gui/$UID_N/com.govaios.guard" 2>/dev/null || true
launchctl bootout "gui/$UID_N/com.govaios.panel" 2>/dev/null || true
rm -rf "/Applications/gov-aios.app"
mv "$STAGE/gov-aios.app" /Applications/gov-aios.app

if [ -n "$SETTINGS" ]; then
  mv -f "$MS_TMP" "$MS_DIR/managed-settings.json"
elif [ -e "$MS_DIR/managed-settings.json" ]; then
  echo "note: --no-claude keeps the existing managed settings"
fi

# The plist is written as the user, so root never writes through user-owned paths.
sudo -u "$SUDO_USER" /bin/mkdir -p "$AGENTS"
sudo -u "$SUDO_USER" /usr/bin/install -m 0644 packaging/com.govaios.guard.plist "$PLIST"
sudo -u "$SUDO_USER" /usr/bin/install -m 0644 packaging/com.govaios.panel.plist "$PANEL_PLIST"

cat <<MSG
Installed $APP${SETTINGS:+ and managed settings}.
Now, in System Settings > Privacy & Security, add $APP to:
  - Accessibility
  - Screen Recording
(this script changes no TCC setting). Then run: bin/gov-aios doctor
MSG

boot() { # label plist
  for i in 1 2 3; do
    launchctl bootstrap "gui/$UID_N" "$2" && return 0
    [ "$i" -eq 3 ] || sleep 1
  done
  echo "bootstrap failed; run: launchctl bootstrap gui/$UID_N \"$2\"" >&2
  exit 1
}
boot guard "$PLIST"
# Warn only. Our own gov-aios (a reinstall) is ignored, decided by lsof's command name.
OTHER=$(lsof -nP -iTCP:8765 -sTCP:LISTEN -Fc 2>/dev/null | sed -n 's/^c//p' | grep -vx 'gov-aios' | head -n 1 || true)
[ -z "$OTHER" ] || echo "warning: port 8765 is in use by $OTHER" >&2
boot panel "$PANEL_PLIST"
echo "Control panel: http://127.0.0.1:8765/  (sign in with Touch ID on the page)"
