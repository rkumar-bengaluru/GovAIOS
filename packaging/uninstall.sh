#!/bin/bash
# Run by the admin: sudo packaging/uninstall.sh. Never touches the data home or the audit log.
# Root writes nothing through user-owned paths: the user's plist is removed as the user (as install.sh).
set -euo pipefail
export PATH=/usr/bin:/bin:/usr/sbin:/sbin
unset PYTHONPATH PYTHONHOME

[ "$(id -u)" -eq 0 ] && [ -n "${SUDO_USER:-}" ] || { echo "run with sudo, as a normal user: sudo packaging/uninstall.sh" >&2; exit 1; }
[ "$SUDO_USER" != root ] || { echo "SUDO_USER is root" >&2; exit 1; }
# Under sudo $HOME is root's: take the user's home from the password database (spaces and newlines safe).
UHOME=$(/usr/bin/python3 -I -c 'import pwd,sys;print(pwd.getpwnam(sys.argv[1]).pw_dir)' "$SUDO_USER")
UID_N=$(id -u "$SUDO_USER")
[ "$UID_N" -ne 0 ] || { echo "refusing: $SUDO_USER has uid 0" >&2; exit 1; }
[ -n "$UHOME" ] && [ -d "$UHOME" ] || { echo "cannot resolve home of $SUDO_USER" >&2; exit 1; }

launchctl bootout "gui/$UID_N/com.govaios.guard" 2>/dev/null || true
sudo -u "$SUDO_USER" rm -f "$UHOME/Library/LaunchAgents/com.govaios.guard.plist"
rm -f "/Library/Application Support/ClaudeCode/managed-settings.json"
rm -rf /Applications/gov-aios.app

echo "Uninstalled. Remove the TCC entries in System Settings yourself. The data home and audit log are kept."
