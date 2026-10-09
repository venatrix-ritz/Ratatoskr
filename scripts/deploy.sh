#!/usr/bin/env bash
# Deploy Ratatoskr (formerly Touch Master) to the AYN Thor handheld device.
set -euo pipefail

# Host: arg 1, $THOR_HOST, $THOR_ENV_FILE, ./local/thor.env, or ../../local/thor.env (when reached through the AynThor
# plugins/ junction). Keep the address out of tracked files; template: scripts/thor.env.example.
_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -z "${THOR_HOST:-}" ]; then
    for _f in "${THOR_ENV_FILE:-}" "${_ROOT}/local/thor.env" "${_ROOT}/../../local/thor.env"; do
        if [ -n "$_f" ] && [ -f "$_f" ]; then THOR_HOST="$(sed -n 's/^THOR_HOST=//p' "$_f" | head -1)"; break; fi
    done
fi
THOR_HOST="${1:-${THOR_HOST:-}}"
[ -n "$THOR_HOST" ] || { echo "ERROR: no Thor host. Pass it as arg 1, set THOR_HOST, or fill local/thor.env." >&2; exit 2; }
PLUGIN_DIR="/home/armada/homebrew/plugins/thor-input"
APP_DIR="/var/home/armada/.local/share/thor-input"

echo "==> Deploying Ratatoskr to ${THOR_HOST}..."

# 1. Prepare remote directories
ssh "${THOR_HOST}" "
    mkdir -p '${APP_DIR}/bin'
    sudo mkdir -p '${PLUGIN_DIR}/dist'
"

# 2. Sync backend app & diagnostics
echo "==> Syncing backend engine & diagnostics..."
scp debug_codes.py "${THOR_HOST}:${APP_DIR}/"
scp bin/*.py "${THOR_HOST}:${APP_DIR}/bin/"
ssh "${THOR_HOST}" "chmod +x '${APP_DIR}/bin/thor_app.py' '${APP_DIR}/bin/touch_master_manager.py'"

# 3. Sync Standalone App Desktop Entry & Icon
echo "==> Syncing standalone app launcher & icon..."
ssh "${THOR_HOST}" "mkdir -p ~/.local/share/applications ~/.local/share/icons/hicolor/scalable/apps"
scp touch-master.desktop "${THOR_HOST}:~/.local/share/applications/touch-master.desktop"
scp touch-master-stop.desktop "${THOR_HOST}:~/.local/share/applications/touch-master-stop.desktop"
scp touch-master.svg "${THOR_HOST}:~/.local/share/icons/hicolor/scalable/apps/touch-master.svg"
ssh "${THOR_HOST}" "
    chmod +x ~/.local/share/applications/touch-master.desktop ~/.local/share/applications/touch-master-stop.desktop
    update-desktop-database ~/.local/share/applications 2>/dev/null || true
    gtk-update-icon-cache -f ~/.local/share/icons/hicolor 2>/dev/null || true
    kbuildsycoca6 2>/dev/null || true
"

# 4. Sync systemd user service unit
echo "==> Syncing systemd user service..."
ssh "${THOR_HOST}" "mkdir -p ~/.config/systemd/user"
scp systemd/touch-master.service "${THOR_HOST}:~/.config/systemd/user/touch-master.service"
ssh "${THOR_HOST}" "systemctl --user daemon-reload"

# 5. Sync Decky plugin files
echo "==> Syncing Decky plugin files..."
scp plugin.json "${THOR_HOST}:/tmp/plugin.json"
scp package.json "${THOR_HOST}:/tmp/package.json"
scp debug_codes.py "${THOR_HOST}:/tmp/debug_codes.py"
scp main.py "${THOR_HOST}:/tmp/main.py"
scp dist/index.js "${THOR_HOST}:/tmp/index.js"

ssh "${THOR_HOST}" "
    sudo mv /tmp/plugin.json /tmp/package.json /tmp/main.py /tmp/debug_codes.py '${PLUGIN_DIR}/'
    sudo mv /tmp/index.js '${PLUGIN_DIR}/dist/index.js'
    # A release-zip install leaves driver/ here; main.py would copy it over the files just deployed (it did, 2026-10-08).
    sudo rm -rf '${PLUGIN_DIR}/driver'
    sudo chown -R root:root '${PLUGIN_DIR}'
    sudo chmod -R 755 '${PLUGIN_DIR}'
    echo '==> Restarting plugin_loader.service...'
    sudo systemctl restart plugin_loader.service
"

echo "==> Restarting the Ratatoskr user service so the new code loads..."
ssh "${THOR_HOST}" "systemctl --user daemon-reload && systemctl --user restart touch-master.service && systemctl --user is-active touch-master.service"

echo "==> Ratatoskr deployed. (Turn on 'Dim bottom screen with the top' in its Decky panel; see systemd/touch-master-backlight.sudoers for the optional narrow sudo rule.)"
