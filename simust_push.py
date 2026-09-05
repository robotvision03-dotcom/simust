"""Push player JSON from the lab PC to the public simust.com host.

Lab keeps full local files (videos, paths). The host only receives a sanitized
session JSON + profile/progress so My SIMUST can show results without opening
the training PC to the internet.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.request
from copy import deepcopy
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

PUSH_URL = os.environ.get("SIMUST_PUSH_URL", "").strip()
PUSH_KEY = os.environ.get("SIMUST_PUSH_KEY", "").strip()
PLAYER_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
QUEUE_DIR = os.environ.get("SIMUST_PUSH_QUEUE", os.path.join(os.path.dirname(os.path.abspath(__file__)), "push_queue"))

os.makedirs(QUEUE_DIR, exist_ok=True)


def push_configured() -> bool:
    return bool(PUSH_URL and PUSH_KEY)


def sanitize_session(session_report: Dict[str, Any]) -> Dict[str, Any]:
    """Drop lab-only secrets: disk paths and huge profile photos."""
    clean = deepcopy(session_report) if session_report else {}
    session = dict(clean.get("session") or {})
    session.pop("directory", None)
    session.pop("original_report_path", None)
    clean["session"] = session
    player = dict(clean.get("player") or {})
    image = player.get("image") or ""
    if isinstance(image, str) and image.startswith("data:"):
        player["image"] = ""
    clean["player"] = player
    return clean


def public_account_payload(username: str, user: Dict[str, Any]) -> Dict[str, Any]:
    """Account fields the host needs to show a dashboard. Never send raw passwords."""
    return {
        "username": username,
        "name": user.get("name", ""),
        "surname": user.get("surname", ""),
        "role": user.get("role", "player"),
        "club": user.get("club", ""),
        "team": user.get("team", ""),
        "age": user.get("age", ""),
        "gender": user.get("gender", ""),
        "email": user.get("email", ""),
        "progress": user.get("progress") or {},
        "password_hash": user.get("password") or "",
    }


def _sign(body: bytes, ts: str) -> str:
    return hmac.new(PUSH_KEY.encode("utf-8"), f"{ts}.".encode("utf-8") + body, hashlib.sha256).hexdigest()


def verify_ingest_headers(key_header: str, ts_header: str, sign_header: str, body: bytes) -> None:
    if not PUSH_KEY:
        raise PermissionError("SIMUST_PUSH_KEY is not set on this host")
    if not key_header or not hmac.compare_digest(key_header, PUSH_KEY):
        raise PermissionError("Invalid push key")
    try:
        ts = int(ts_header or "0")
    except ValueError:
        raise PermissionError("Invalid push timestamp")
    if abs(int(time.time()) - ts) > 300:
        raise PermissionError("Push timestamp too old")
    expect = _sign(body, str(ts))
    if not sign_header or not hmac.compare_digest(sign_header, expect):
        raise PermissionError("Invalid push signature")


def _post(payload: Dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    ts = str(int(time.time()))
    req = urllib.request.Request(
        PUSH_URL,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-SIMUST-PUSH-KEY": PUSH_KEY,
            "X-SIMUST-TS": ts,
            "X-SIMUST-SIGN": _sign(body, ts),
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        if resp.status >= 300:
            raise RuntimeError(f"Push host returned HTTP {resp.status}")


def _queue_path(session_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", session_id or "session")
    return os.path.join(QUEUE_DIR, f"{safe}.json")


def enqueue(payload: Dict[str, Any]) -> None:
    path = _queue_path((payload.get("session") or {}).get("session", {}).get("id") or str(int(time.time())))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    logger.warning("Queued player JSON for later push: %s", path)


def flush_queue() -> int:
    if not push_configured():
        return 0
    sent = 0
    for name in os.listdir(QUEUE_DIR):
        if not name.endswith(".json"):
            continue
        path = os.path.join(QUEUE_DIR, name)
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            _post(payload)
            os.remove(path)
            sent += 1
        except Exception as exc:
            logger.warning("Push queue retry failed for %s: %s", name, exc)
    return sent


def push_session(player_id: str, session_report: Dict[str, Any], user: Optional[Dict[str, Any]], index_entry: Optional[Dict[str, Any]] = None) -> None:
    if not PLAYER_ID_RE.match(player_id or ""):
        logger.warning("Skip push: invalid player_id")
        return
    payload = {
        "player_id": player_id,
        "account": public_account_payload(player_id, user or {}),
        "session": sanitize_session(session_report),
        "index_entry": index_entry or {},
    }
    if not push_configured():
        logger.info("SIMUST_PUSH_URL / SIMUST_PUSH_KEY not set; session stays on this PC only")
        return
    try:
        flush_queue()
        _post(payload)
        logger.info("Pushed session %s for %s to host", (session_report.get("session") or {}).get("id"), player_id)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, RuntimeError, OSError) as exc:
        logger.warning("Push to host failed (%s); will retry from queue", exc)
        enqueue(payload)


def push_session_async(player_id: str, session_report: Dict[str, Any], user: Optional[Dict[str, Any]], index_entry: Optional[Dict[str, Any]] = None) -> None:
    threading.Thread(
        target=push_session,
        args=(player_id, session_report, user, index_entry),
        daemon=True,
        name="simust-push",
    ).start()
