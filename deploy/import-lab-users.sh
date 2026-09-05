#!/bin/bash
# Move a lab users.json uploaded to /tmp onto the public host.
# On the Windows lab PC:
#   scp users.json root@YOUR_VPS_IP:/tmp/users.json
# Then on the VPS:
#   bash /opt/simust/deploy/import-lab-users.sh
set -euo pipefail
APP_DIR=/opt/simust
SRC="${1:-/tmp/users.json}"

if [ ! -f "$SRC" ]; then
  echo "Missing $SRC"
  echo "From the lab PC copy users.json first:"
  echo "  scp users.json root@$(curl -4 -fsS https://ifconfig.me):/tmp/users.json"
  exit 1
fi

python3 - "$SRC" <<'PY'
import json, sys
path = sys.argv[1]
with open(path, encoding="utf-8") as f:
    users = json.load(f)
if not isinstance(users, dict) or not users:
    raise SystemExit("users.json is empty or not an object")
print("accounts", len(users))
PY

install -m 640 -o simust -g simust "$SRC" "$APP_DIR/users.json"
systemctl restart simust
echo "Imported lab accounts. Try http://$(curl -4 -fsS https://ifconfig.me)/login"
