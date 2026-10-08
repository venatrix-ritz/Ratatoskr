#!/usr/bin/env bash
# Install only the Decky panel files (main.py, dist/index.js, plugin.json, package.json, debug_codes.py) on the Thor
# and restart Decky Loader. The driver itself is deployed by deploy.sh or by hand; this script does not touch it.
# The plugin folder is root-owned, so this needs sudo on the Thor, and restarting plugin_loader.service briefly
# reloads Decky's plugins in Game Mode.
set -euo pipefail

_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -z "${THOR_HOST:-}" ]; then
    for _f in "${THOR_ENV_FILE:-}" "${_ROOT}/local/thor.env" "${_ROOT}/../../local/thor.env"; do
        if [ -n "$_f" ] && [ -f "$_f" ]; then THOR_HOST="$(sed -n 's/^THOR_HOST=//p' "$_f" | head -1)"; break; fi
    done
fi
THOR_HOST="${1:-${THOR_HOST:-}}"
[ -n "$THOR_HOST" ] || { echo "ERROR: no Thor host. Pass it as arg 1, set THOR_HOST, or fill local/thor.env." >&2; exit 2; }
PLUGIN_DIR="/home/armada/homebrew/plugins/thor-input"

cd "$_ROOT"
echo "==> Copying the Decky panel files to ${THOR_HOST}..."
scp plugin.json package.json debug_codes.py main.py dist/index.js "${THOR_HOST}:/tmp/"

ssh "${THOR_HOST}" "
    set -e
    sudo mkdir -p '${PLUGIN_DIR}/dist'
    sudo mv /tmp/plugin.json /tmp/package.json /tmp/main.py /tmp/debug_codes.py '${PLUGIN_DIR}/'
    sudo mv /tmp/index.js '${PLUGIN_DIR}/dist/index.js'
    sudo chown -R root:root '${PLUGIN_DIR}'
    sudo chmod -R 755 '${PLUGIN_DIR}'
    echo '==> Restarting plugin_loader.service...'
    sudo systemctl restart plugin_loader.service
"
echo "==> Done. Open the Ratatoskr panel in Decky: there is now a 'Pen' section (Pen mode and Pen +)."
