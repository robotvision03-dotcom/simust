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
# Install unit file so TimeoutStopSec/KillMode apply (avoids hung restarts).
if [ -f "$APP_DIR/deploy/simust.service" ]; then
  cp "$APP_DIR/deploy/simust.service" /etc/systemd/system/simust.service
  systemctl daemon-reload
fi
# Never block forever on a wedged worker: stop with short timeout, then kill leftovers.
systemctl stop simust || true
sleep 1
# Anything still holding :8000 after TimeoutStopSec
if command -v fuser >/dev/null 2>&1; then
  fuser -k 8000/tcp 2>/dev/null || true
fi
pkill -9 -f '/opt/simust/.venv/bin/python /opt/simust/app.py' 2>/dev/null || true
systemctl start simust
sleep 2
systemctl --no-pager --full status simust | head -n 25

echo "==> Refreshing Caddy (public :80/:443 → 127.0.0.1:8000)"
if [ -f "$APP_DIR/deploy/Caddyfile" ]; then
  cp "$APP_DIR/deploy/Caddyfile" /etc/caddy/Caddyfile
fi
systemctl restart caddy
sleep 2
systemctl --no-pager --full status caddy | head -n 20
curl -sS -m 8 -o /dev/null -w "public_operator:%{http_code} t:%{time_total}\n" https://my.simust.com/operator || true
curl -sS -m 5 http://127.0.0.1:8000/lab-link || true
echo
echo "==> Done. Portal: https://my.simust.com/login"
