#!/bin/bash
# Install My SIMUST on a fresh Ubuntu 24.04 Hetzner Cloud server.
# Run as root after you can SSH in:
#   curl -fsSL https://raw.githubusercontent.com/robotvision03-dotcom/simust/main/deploy/hetzner-setup.sh
#   sudo bash hetzner-setup.sh
set -euo pipefail

REPO_URL="${SIMUST_REPO_URL:-https://github.com/robotvision03-dotcom/simust.git}"
REPO_BRANCH="${SIMUST_REPO_BRANCH:-cursor/hetzner-public-host-c690}"
APP_DIR=/opt/simust
DOMAIN="${SIMUST_DOMAIN:-my.simust.com}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ "$(id -u)" -ne 0 ]; then
  echo "Run this script as root: sudo bash deploy/hetzner-setup.sh"
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3 python3-venv python3-pip git rsync ufw debian-keyring debian-archive-keyring apt-transport-https curl gpg

if ! command -v caddy >/dev/null 2>&1; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
    | tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
  apt-get update
  apt-get install -y caddy
fi

id -u simust >/dev/null 2>&1 || useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin simust

if [ -f "$SCRIPT_DIR/../app.py" ] && [ "$SCRIPT_DIR" != "$APP_DIR/deploy" ]; then
  mkdir -p "$APP_DIR"
  rsync -a --exclude '.venv' --exclude '.env' "$SCRIPT_DIR/../" "$APP_DIR/"
elif [ ! -d "$APP_DIR/.git" ]; then
  git clone --branch "$REPO_BRANCH" "$REPO_URL" "$APP_DIR"
else
  git -C "$APP_DIR" fetch origin
  git -C "$APP_DIR" checkout "$REPO_BRANCH"
  git -C "$APP_DIR" pull --ff-only origin "$REPO_BRANCH"
fi

python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements-public.txt"

if [ ! -f "$APP_DIR/.env" ]; then
  SESSION_SECRET="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
  PUSH_KEY="$(python3 -c 'import secrets; print(secrets.token_hex(24))')"
  cat > "$APP_DIR/.env" <<EOF
SIMUST_PUBLIC_MODE=1
SIMUST_HOST=127.0.0.1
SIMUST_PORT=8000
SIMUST_PUBLIC_ORIGINS=https://simust.com,https://www.simust.com,https://${DOMAIN}
SIMUST_SESSION_SECRET=${SESSION_SECRET}
SIMUST_PUSH_KEY=${PUSH_KEY}
SIMUST_REPORTS_DIR=${APP_DIR}/simust_reports
SIMUST_PLAYER_DIRECTORY=${APP_DIR}/simust_player
EOF
  echo
  echo "Saved secrets in ${APP_DIR}/.env"
  echo "Lab PC needs this push key (keep it private):"
  echo "  SIMUST_PUSH_KEY=${PUSH_KEY}"
  echo "  SIMUST_PUSH_URL=https://${DOMAIN}/internal/ingest-player-data"
  echo
fi

mkdir -p "$APP_DIR/simust_reports" "$APP_DIR/simust_player"
chown -R simust:simust "$APP_DIR"
chmod 640 "$APP_DIR/.env"

install -m 644 "$APP_DIR/deploy/simust.service" /etc/systemd/system/simust.service
install -m 644 "$APP_DIR/deploy/Caddyfile" /etc/caddy/Caddyfile
sed -i "s/my.simust.com/${DOMAIN}/g" /etc/caddy/Caddyfile

ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

systemctl daemon-reload
systemctl enable --now simust
systemctl enable --now caddy
systemctl restart simust
systemctl reload caddy

PUBLIC_IP="$(curl -4 -fsS https://ifconfig.me || hostname -I | awk '{print $1}')"
echo
echo "Hetzner install finished."
echo "1. DNS A record:  ${DOMAIN}  ->  ${PUBLIC_IP}"
echo "2. Wait a few minutes, then open https://${DOMAIN}/login"
echo "3. On the lab PC set SIMUST_PUSH_URL and SIMUST_PUSH_KEY from ${APP_DIR}/.env"
