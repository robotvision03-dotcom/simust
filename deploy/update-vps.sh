#!/bin/bash
# Update My SIMUST on the Hetzner VPS from git, then restart the service.
#
# Run on the VPS as root. sudo drops exported variables, so pass the branch
# as an argument (default: main):
#   sudo bash /opt/simust/deploy/update-vps.sh simust_development_entry
#
# This also works with the script already on the server:
#   sudo env SIMUST_REPO_BRANCH=simust_development_entry bash /opt/simust/deploy/update-vps.sh
#
# SIMUST_APP_DIR=/opt/simust
set -euo pipefail

APP_DIR="${SIMUST_APP_DIR:-/opt/simust}"
BRANCH="${1:-${SIMUST_REPO_BRANCH:-main}}"

if [ "$(id -u)" -ne 0 ]; then
  echo "Run as root: sudo bash deploy/update-vps.sh"
  exit 1
fi

if [ ! -d "$APP_DIR/.git" ]; then
  echo "No git repo at $APP_DIR — run deploy/hetzner-setup.sh first."
  exit 1
fi

echo "==> Updating $APP_DIR from origin/$BRANCH"
cd "$APP_DIR"
git fetch origin
git checkout "$BRANCH"
git pull --ff-only origin "$BRANCH"

if [ -f "$APP_DIR/requirements-public.txt" ] && [ -x "$APP_DIR/.venv/bin/pip" ]; then
  echo "==> Syncing Python deps"
  "$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements-public.txt"
fi

echo "==> Restarting simust"
systemctl restart simust
systemctl --no-pager --full status simust | head -n 20
echo "==> Done. Portal: https://my.simust.com/login"
