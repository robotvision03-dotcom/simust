#!/bin/bash
# Update My SIMUST on the Hetzner VPS from git, then restart the service.
#
# Run on the VPS as root:
#   sudo bash /opt/simust/deploy/update-vps.sh
#
# Or from your PC (with SSH key):
#   ssh root@157.180.47.98 'bash /opt/simust/deploy/update-vps.sh'
#
# Env overrides:
#   SIMUST_REPO_BRANCH=main   (default: main)
#   SIMUST_APP_DIR=/opt/simust
set -euo pipefail

APP_DIR="${SIMUST_APP_DIR:-/opt/simust}"
BRANCH="${SIMUST_REPO_BRANCH:-main}"

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
