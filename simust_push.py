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
_users_pull_lock = threading.Lock()
_users_pull_at = 0.0
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


def export_accounts_url() -> str:
    if not PUSH_URL:
        return ""
    if PUSH_URL.rstrip("/").endswith("/internal/ingest-player-data"):
        return PUSH_URL.replace("/internal/ingest-player-data", "/internal/export-accounts")
    return PUSH_URL.rsplit("/", 1)[0] + "/export-accounts"


def export_remote_commands_url() -> str:
    if not PUSH_URL:
        return ""
    if PUSH_URL.rstrip("/").endswith("/internal/ingest-player-data"):
        return PUSH_URL.replace("/internal/ingest-player-data", "/internal/export-remote-commands")
    return PUSH_URL.rsplit("/", 1)[0] + "/export-remote-commands"


def pull_remote_accounts() -> Dict[str, Any]:
    """Lab PC: download accounts registered on My SIMUST."""
    url = export_accounts_url()
    if not url or not PUSH_KEY:
        return {}
    ts = str(int(time.time()))
    body = b""
    req = urllib.request.Request(
        url,
        method="GET",
        headers={
            "X-SIMUST-PUSH-KEY": PUSH_KEY,
            "X-SIMUST-TS": ts,
            "X-SIMUST-SIGN": _sign(body, ts),
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    accounts = data.get("accounts") if isinstance(data, dict) else None
    return accounts if isinstance(accounts, dict) else {}


def pull_remote_state() -> Dict[str, Any]:
    url = export_accounts_url()
    if not url or not PUSH_KEY:
        return {}
    ts = str(int(time.time()))
    body = b""
    req = urllib.request.Request(
        url,
        method="GET",
        headers={
            "X-SIMUST-PUSH-KEY": PUSH_KEY,
            "X-SIMUST-TS": ts,
            "X-SIMUST-SIGN": _sign(body, ts),
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data if isinstance(data, dict) else {}


def merge_remote_reservations(local: list, remote: list, prune_source: str = "", deleted_ids=None) -> int:
    """Union reservations by id. Optionally drop cancelled ids or stale rows from one source."""
    if local is None:
        local = []
    deleted = {item for item in (deleted_ids or []) if item}
    if deleted:
        kept = [item for item in local if item.get("id") not in deleted]
        local[:] = kept
    if prune_source:
        remote_ids = {item.get("id") for item in (remote or []) if item.get("id")}
        local[:] = [
            item for item in local
            if (item.get("source") or "") != prune_source or item.get("id") in remote_ids
        ]
    by_id = {item.get("id"): item for item in local if item.get("id")}
    added = 0
    for item in remote or []:
        rid = (item or {}).get("id")
        if not rid or rid in deleted or rid in by_id:
            continue
        local.append(item)
        added += 1
    return added


def merge_remote_accounts(local: Dict[str, Any], remote: Dict[str, Any]) -> list:
    """Add VPS-only users to the lab list. Does not overwrite existing lab passwords."""
    added = []
    for username, account in (remote or {}).items():
        username = (username or "").strip()
        if not PLAYER_ID_RE.match(username):
            continue
        account = account or {}
        if username not in local:
            local[username] = {
                "password": account.get("password_hash") or "",
                "name": account.get("name", ""),
                "surname": account.get("surname", ""),
                "role": account.get("role") or "player",
                "club": account.get("club", ""),
                "team": account.get("team", ""),
                "age": account.get("age", ""),
                "gender": account.get("gender", ""),
                "email": account.get("email", ""),
                "progress": account.get("progress") or {
                    "current_level": "L00-Foundation",
                    "unlocked_levels": ["L00-Foundation"],
                    "completed_levels": [],
                    "challenge_results": {},
                },
            }
            added.append(username)
            continue
        existing = local[username]
        for field in ("name", "surname", "role", "club", "team", "age", "gender", "email"):
            if not existing.get(field) and account.get(field):
                existing[field] = account[field]
        if account.get("progress") and not existing.get("progress"):
            existing["progress"] = account["progress"]
        if account.get("password_hash") and not existing.get("password"):
            existing["password"] = account["password_hash"]
    return added


def pull_and_merge_accounts(
    load_users_fn,
    save_users_fn,
    reports_dir: str = "",
    load_reservations_fn=None,
    save_reservations_fn=None,
) -> list:
    global _users_pull_at
    now = time.time()
    with _users_pull_lock:
        if now - _users_pull_at < 8:
            return []
        _users_pull_at = now
    if not push_configured():
        return []
    try:
        remote = pull_remote_state()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, RuntimeError, OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not pull My SIMUST accounts: %s", exc)
        return []
    remote_accounts = remote.get("accounts") if isinstance(remote.get("accounts"), dict) else {}
    added = []
    if remote_accounts:
        local = load_users_fn()
        added = merge_remote_accounts(local, remote_accounts)
        if added:
            save_users_fn(local)
            if reports_dir:
                for username in added:
                    try:
                        folder = os.path.join(reports_dir, username)
                        os.makedirs(folder, exist_ok=True)
                        index_path = os.path.join(folder, "index.json")
                        if not os.path.isfile(index_path):
                            with open(index_path, "w", encoding="utf-8") as f:
                                json.dump([], f)
                    except OSError:
                        pass
            logger.info("Imported %s My SIMUST account(s) into the lab: %s", len(added), ", ".join(added))
    if load_reservations_fn and save_reservations_fn:
        remote_res = remote.get("reservations")
        if isinstance(remote_res, list) and remote_res:
            local_res = load_reservations_fn() or []
            added_res = merge_remote_reservations(local_res, remote_res, prune_source="public")
            save_reservations_fn(local_res)
            if added_res:
                logger.info("Imported %s reservation(s) from My SIMUST", added_res)
    return added


def push_reservations(items: list, deleted_ids=None) -> None:
    if not push_configured():
        return
    payload = {"kind": "reservations", "reservations": items or [], "deleted_ids": list(deleted_ids or [])}
    try:
        _post(payload)
    except Exception as exc:
        logger.warning("Reservation push failed: %s", exc)
        enqueue(payload)


def push_reservations_async(items: list, deleted_ids=None) -> None:
    threading.Thread(
        target=push_reservations,
        args=(items, deleted_ids),
        daemon=True,
        name="simust-push-res",
    ).start()


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


def pull_remote_commands() -> list:
    url = export_remote_commands_url()
    if not url or not PUSH_KEY:
        return []
    ts = str(int(time.time()))
    body = b""
    req = urllib.request.Request(
        url,
        method="GET",
        headers={
            "X-SIMUST-PUSH-KEY": PUSH_KEY,
            "X-SIMUST-TS": ts,
            "X-SIMUST-SIGN": _sign(body, ts),
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    commands = data.get("commands") if isinstance(data, dict) else None
    return commands if isinstance(commands, list) else []


def push_lab_status(status: Dict[str, Any]) -> None:
    if not push_configured():
        return
    try:
        _post({"kind": "lab_status", "status": status or {}})
    except Exception as exc:
        logger.warning("Lab status push failed: %s", exc)
