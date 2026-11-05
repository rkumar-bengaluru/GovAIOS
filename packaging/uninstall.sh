#!/bin/bash
# Run by the admin: sudo packaging/uninstall.sh. Never touches the data home or the audit log.
set -euo pipefail

[ "$(id -u)" -eq 0 ] && [ -n "${SUDO_USER:-}" ] || { echo "run with sudo, as a normal user: sudo packaging/uninstall.sh" >&2; exit 1; }
UHOME=$(/usr/bin/dscl . -read "/Users/$SUDO_USER" NFSHomeDirectory | /usr/bin/awk '{print $2}')
UID_N=$(id -u "$SUDO_USER")
[ -n "$UHOME" ] || { echo "cannot resolve home of $SUDO_USER" >&2; exit 1; }

launchctl bootout "gui/$UID_N/com.govaios.guard" 2>/dev/null || true
rm -f "$UHOME/Library/LaunchAgents/com.govaios.guard.plist"
rm -f "/Library/Application Support/ClaudeCode/managed-settings.json"
rm -rf /Applications/gov-aios.app

echo "Uninstalled. Remove the TCC entries in System Settings yourself. The data home and audit log are kept."
