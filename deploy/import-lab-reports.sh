#!/bin/bash
# Import JSON reports copied from the lab PC.
# On Windows:
#   scp -r "C:\Users\siama\Documents\simust_reports\*" root@157.180.47.98:/tmp/simust_reports/
# Then:
#   bash /opt/simust/deploy/import-lab-reports.sh
set -euo pipefail
SRC="${1:-/tmp/simust_reports}"
DEST=/opt/simust/simust_reports

if [ ! -d "$SRC" ]; then
  echo "Missing $SRC"
  exit 1
fi

python3 - "$SRC" "$DEST" <<'PY'
import json, sys
from pathlib import Path

src, dest = Path(sys.argv[1]), Path(sys.argv[2])
dest.mkdir(parents=True, exist_ok=True)
copied = 0
for player_dir in sorted(p for p in src.iterdir() if p.is_dir()):
    if player_dir.name.startswith("."):
        continue
    out = dest / player_dir.name
    out.mkdir(parents=True, exist_ok=True)
    for path in player_dir.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            print("skip", path, exc)
            continue
        if isinstance(data, dict):
            player = dict(data.get("player") or {})
            image = player.get("image") or ""
            if isinstance(image, str) and image.startswith("data:"):
                player["image"] = ""
            data["player"] = player
            session = dict(data.get("session") or {})
            session.pop("directory", None)
            session.pop("original_report_path", None)
            data["session"] = session
        (out / path.name).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        copied += 1
print("copied_json", copied)
PY

chown -R simust:simust "$DEST"
systemctl restart simust
echo "Reports imported into $DEST"
