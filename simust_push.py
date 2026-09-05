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


def _load_local_env() -> None:
    """Lab PC: read lab.env / .env next to this file. Public host uses systemd env."""
    if os.environ.get("SIMUST_PUBLIC_MODE", "").strip().lower() in ("1", "true", "yes"):
        return
    here = os.path.dirname(os.path.abspath(__file__))
    search = [here, os.getcwd()]
    seen = set()
    for folder in search:
        folder = os.path.abspath(folder)
        if folder in seen:
            continue
        seen.add(folder)
        for name in ("lab.env", ".env"):
            path = os.path.join(folder, name)
            if not os.path.isfile(path):
                continue
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for raw in f:
                        line = raw.strip()
                        if not line or line.startswith("#") or "=" not in line:
                            continue
                        key, value = line.split("=", 1)
                        key = key.strip()
                        value = value.strip().strip('"').strip("'")
                        if key and key not in os.environ:
                            os.environ[key] = value
            except OSError as exc:
                logger.warning("Could not read %s: %s", path, exc)


_load_local_env()
PUSH_URL = os.environ.get("SIMUST_PUSH_URL", "").strip()
PUSH_KEY = os.environ.get("SIMUST_PUSH_KEY", "").strip()
_users_push_lock = threading.Lock()
_users_push_at = 0.0
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
    kind = payload.get("kind") or "session"
    session_id = (payload.get("session") or {}).get("session", {}).get("id") if kind != "accounts" else "accounts"
    path = _queue_path(session_id or str(int(time.time())))
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


def push_accounts(users: Dict[str, Any]) -> None:
    """Send hashed accounts (not raw passwords) so My SIMUST can sign in."""
    if not push_configured():
        logger.info("SIMUST_PUSH_URL / SIMUST_PUSH_KEY not set; accounts stay on this PC only")
        return
    accounts = {}
    for username, user in (users or {}).items():
        if PLAYER_ID_RE.match(username or ""):
            accounts[username] = public_account_payload(username, user or {})
    if not accounts:
        return
    payload = {"kind": "accounts", "accounts": accounts}
    try:
        flush_queue()
        _post(payload)
        logger.info("Pushed %s accounts to the public host", len(accounts))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, RuntimeError, OSError) as exc:
        logger.warning("Account push failed (%s); will retry from queue", exc)
        enqueue(payload)


def push_accounts_async(users: Dict[str, Any]) -> None:
    global _users_push_at
    now = time.time()
    with _users_push_lock:
        if now - _users_push_at < 2:
            return
        _users_push_at = now
    threading.Thread(target=push_accounts, args=(users,), daemon=True, name="simust-push-users").start()


def push_reports_dir(reports_dir: str, users: Optional[Dict[str, Any]] = None) -> int:
    """Push every player JSON under simust_reports (no videos)."""
    if not push_configured():
        logger.info("SIMUST_PUSH_URL / SIMUST_PUSH_KEY not set; reports stay on this PC only")
        return 0
    if not reports_dir or not os.path.isdir(reports_dir):
        logger.warning("Reports folder not found: %s", reports_dir)
        return 0
    users = users or {}
    sent = 0
    players: list = []
    for player_id in sorted(os.listdir(reports_dir)):
        if not PLAYER_ID_RE.match(player_id):
            continue
        player_dir = os.path.join(reports_dir, player_id)
        if not os.path.isdir(player_dir):
            continue
        index_path = os.path.join(player_dir, "index.json")
        index = []
        if os.path.isfile(index_path):
            try:
                with open(index_path, "r", encoding="utf-8") as f:
                    index = json.load(f) or []
            except Exception:
                index = []
        by_file = {row.get("file"): row for row in index if row.get("file")}
        sessions = []
        names = [n for n in os.listdir(player_dir) if n.endswith(".json") and n != "index.json"]
        for name in sorted(names):
            path = os.path.join(player_dir, name)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    report = json.load(f)
            except Exception as exc:
                logger.warning("Skip report %s: %s", path, exc)
                continue
            sessions.append({
                "session": sanitize_session(report if isinstance(report, dict) else {}),
                "index_entry": by_file.get(name) or {},
            })
        if not sessions:
            continue
        players.append({
            "player_id": player_id,
            "account": public_account_payload(player_id, users.get(player_id) or {}),
            "sessions": sessions,
        })
        # Send one player per request so a 2 GB host is not overloaded.
        payload = {"kind": "reports", "players": [players[-1]]}
        try:
            flush_queue()
            _post(payload)
            sent += len(sessions)
            logger.info("Pushed %s reports for %s", len(sessions), player_id)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, RuntimeError, OSError) as exc:
            logger.warning("Report push failed for %s (%s); queued", player_id, exc)
            enqueue(payload)
    return sent


def push_reports_async(reports_dir: str, users: Optional[Dict[str, Any]] = None) -> None:
    threading.Thread(
        target=push_reports_dir,
        args=(reports_dir, users),
        daemon=True,
        name="simust-push-reports",
    ).start()


def push_live_session(player_id: str, session_report: Dict[str, Any], user: Optional[Dict[str, Any]]) -> None:
    """Overwrite one live_{player} session on the host while a test is running."""
    live = sanitize_session(session_report)
    session = dict(live.get("session") or {})
    session["id"] = f"live_{player_id}"
    session["live"] = True
    live["session"] = session
    index_entry = {
        "session_id": session["id"],
        "timestamp": session.get("timestamp") or "",
        "level": session.get("level") or "live",
        "live": True,
        "total_actions": live.get("total_actions") or 0,
        "correct": (live.get("statistics") or {}).get("correct", 0),
        "late": (live.get("statistics") or {}).get("late", 0),
        "wrong": (live.get("statistics") or {}).get("wrong", 0),
        "file": f"{session['id']}.json",
    }
    push_session(player_id, live, user, index_entry)
