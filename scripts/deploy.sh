#!/usr/bin/env bash
# Deploy Thor Input to the AYN Thor handheld device.
set -euo pipefail

THOR_HOST="${1:-armada@<thor-ip>}"
PLUGIN_DIR="/home/armada/homebrew/plugins/thor-input"
APP_DIR="/var/home/armada/.local/share/thor-input"

echo "==> Deploying Thor Input to ${THOR_HOST}..."

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

# 4. Sync Decky plugin files
echo "==> Syncing Decky plugin files..."
scp plugin.json "${THOR_HOST}:/tmp/plugin.json"
scp package.json "${THOR_HOST}:/tmp/package.json"
scp debug_codes.py "${THOR_HOST}:/tmp/debug_codes.py"
scp main.py "${THOR_HOST}:/tmp/main.py"
scp dist/index.js "${THOR_HOST}:/tmp/index.js"

ssh "${THOR_HOST}" "
    sudo mv /tmp/plugin.json /tmp/package.json /tmp/main.py /tmp/debug_codes.py '${PLUGIN_DIR}/'
    sudo mv /tmp/index.js '${PLUGIN_DIR}/dist/index.js'
    sudo chown -R root:root '${PLUGIN_DIR}'
    sudo chmod -R 755 '${PLUGIN_DIR}'
    echo '==> Restarting plugin_loader.service...'
    sudo systemctl restart plugin_loader.service
"

echo "==> Thor Input successfully deployed and active!"
