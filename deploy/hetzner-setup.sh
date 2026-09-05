#!/bin/bash
# Install My SIMUST on a Hetzner Ubuntu cloud server (24.04 or 26.04).
#
# From a fresh server (you are already root), paste:
#   apt-get update && apt-get install -y curl
#   curl -fsSL https://raw.githubusercontent.com/robotvision03-dotcom/simust/cursor/arena-simulation/deploy/hetzner-setup.sh -o hetzner-setup.sh
#   bash hetzner-setup.sh
set -euo pipefail

REPO_URL="${SIMUST_REPO_URL:-https://github.com/robotvision03-dotcom/simust.git}"
REPO_BRANCH="${SIMUST_REPO_BRANCH:-cursor/arena-simulation}"
APP_DIR=/opt/simust
DOMAIN="${SIMUST_DOMAIN:-my.simust.com}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CADDY_VERSION="${CADDY_VERSION:-2.10.2}"

if [ "$(id -u)" -ne 0 ]; then
  echo "Run this script as root: sudo bash hetzner-setup.sh"
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3 python3-venv python3-pip git rsync ufw curl ca-certificates tar

install_caddy() {
  if command -v caddy >/dev/null 2>&1; then
    return
  fi
  arch="$(uname -m)"
  case "$arch" in
    x86_64) caddy_arch=amd64 ;;
    aarch64|arm64) caddy_arch=arm64 ;;
    *) echo "Unsupported architecture: $arch"; exit 1 ;;
  esac
  tmp="$(mktemp -d)"
  curl -fsSL "https://github.com/caddyserver/caddy/releases/download/v${CADDY_VERSION}/caddy_${CADDY_VERSION}_linux_${caddy_arch}.tar.gz" \
    -o "$tmp/caddy.tgz"
  tar -C "$tmp" -xzf "$tmp/caddy.tgz" caddy
  install -m 755 "$tmp/caddy" /usr/bin/caddy
  rm -rf "$tmp"
  id -u caddy >/dev/null 2>&1 || useradd --system --home /var/lib/caddy --shell /usr/sbin/nologin caddy
  mkdir -p /var/lib/caddy /etc/caddy
  chown -R caddy:caddy /var/lib/caddy
}

install_caddy

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
if [ ! -f /etc/systemd/system/caddy.service ] && [ ! -f /lib/systemd/system/caddy.service ]; then
  install -m 644 "$APP_DIR/deploy/caddy.service" /etc/systemd/system/caddy.service
fi
install -m 644 "$APP_DIR/deploy/Caddyfile" /etc/caddy/Caddyfile
if [ "$DOMAIN" != "my.simust.com" ]; then
  sed -i "s/my.simust.com/${DOMAIN}/g" /etc/caddy/Caddyfile
fi

ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

systemctl daemon-reload
systemctl enable --now simust
systemctl restart simust
systemctl enable caddy
if ! systemctl restart caddy; then
  echo "Caddy HTTPS not ready yet (DNS may still point elsewhere). Serving HTTP only."
  cat > /etc/caddy/Caddyfile <<EOF
:80 {
	reverse_proxy 127.0.0.1:8000
}
EOF
  systemctl restart caddy
fi

PUBLIC_IP="$(curl -4 -fsS https://ifconfig.me || hostname -I | awk '{print $1}')"
echo
echo "Hetzner install finished."
echo "This server IPv4: ${PUBLIC_IP}"
echo "1. DNS A record must be:  ${DOMAIN}  ->  ${PUBLIC_IP}"
echo "2. Test now:  http://${PUBLIC_IP}/login"
echo "3. After DNS: https://${DOMAIN}/login"
echo "4. On the lab PC set SIMUST_PUSH_URL and SIMUST_PUSH_KEY from ${APP_DIR}/.env"
