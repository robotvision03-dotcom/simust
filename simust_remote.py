"""Queue lab operator commands from the public Android / tablet UI."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

ALLOWED_ACTIONS = {
    "start-realtime-playback",
    "stop-realtime",
    "pause-realtime",
    "set-simulation",
    "set-visualization",
    "lab-upsert-player",
    "unlock-level",
    "lock-level",
}

GET_STATUS_KEYS = {
    "playback-status": "playback-status",
    "realtime-results": "realtime-results",
    "results": "results",
}

COMMANDS_FILE = os.environ.get("SIMUST_REMOTE_FILE", "remote_commands.json")
REMOTE_COMMAND_TTL_SEC = int(os.environ.get("SIMUST_REMOTE_COMMAND_TTL", "90"))
_LOCK = threading.Lock()


def _empty_state() -> Dict[str, Any]:
    return {"pending": [], "status": {"lab_online": False, "updated_at": ""}}


def _load() -> Dict[str, Any]:
    if not os.path.isfile(COMMANDS_FILE):
        return _empty_state()
    try:
        with open(COMMANDS_FILE, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            return _empty_state()
        data.setdefault("pending", [])
        data.setdefault("status", {})
        return data
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not read remote command file: %s", exc)
        return _empty_state()


def _save(state: Dict[str, Any]) -> None:
    tmp = COMMANDS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2, ensure_ascii=False)
    os.replace(tmp, COMMANDS_FILE)


def _created_ts(item: Dict[str, Any]) -> Optional[float]:
    created = (item or {}).get("created_at") or ""
    try:
        return time.mktime(time.strptime(str(created)[:19], "%Y-%m-%dT%H:%M:%S"))
    except (ValueError, OverflowError, OSError, TypeError):
        return None


def _fresh_pending(pending: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    now = time.time()
    fresh = []
    for row in pending:
        if not isinstance(row, dict):
            continue
        created = _created_ts(row)
        if created is not None and (now - created) > REMOTE_COMMAND_TTL_SEC:
            continue
        fresh.append(row)
    return fresh


def enqueue(action: str, payload: Dict[str, Any], actor: str) -> Dict[str, Any]:
    action = (action or "").strip().lstrip("/")
    if action not in ALLOWED_ACTIONS:
        raise ValueError("Unsupported operator action")
    item = {
        "id": str(uuid.uuid4()),
        "action": action,
        "payload": payload or {},
        "actor": actor or "",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    with _LOCK:
        state = _load()
        pending = _fresh_pending([row for row in state.get("pending") or [] if isinstance(row, dict)])
        pending.append(item)
        state["pending"] = pending[-50:]
        _save(state)
    return item


def take_pending(limit: int = 20) -> List[Dict[str, Any]]:
    with _LOCK:
        state = _load()
        pending = _fresh_pending([row for row in state.get("pending") or [] if isinstance(row, dict)])
        taken = pending[: max(1, int(limit))] if pending else []
        state["pending"] = pending[len(taken) :]
        _save(state)
    return taken


def peek_pending(limit: int = 20) -> List[Dict[str, Any]]:
    with _LOCK:
        state = _load()
        pending = _fresh_pending([row for row in state.get("pending") or [] if isinstance(row, dict)])
        if pending != (state.get("pending") or []):
            state["pending"] = pending
            _save(state)
    return pending[: max(1, int(limit))] if pending else []


def ack_ids(ids) -> int:
    drop = {item for item in (ids or []) if item}
    if not drop:
        return 0
    with _LOCK:
        state = _load()
        pending = _fresh_pending([row for row in state.get("pending") or [] if isinstance(row, dict)])
        kept = [row for row in pending if row.get("id") not in drop]
        state["pending"] = kept
        _save(state)
        return len(pending) - len(kept)


def set_status(status: Dict[str, Any]) -> None:
    with _LOCK:
        state = _load()
        merged = dict(state.get("status") or {})
        merged.update(status or {})
        merged["lab_online"] = True
        merged["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        state["status"] = merged
        _save(state)


def get_status() -> Dict[str, Any]:
    with _LOCK:
        status = dict((_load().get("status") or {}))
    updated = status.get("updated_at") or ""
    if updated:
        try:
            stamp = time.strptime(updated[:19], "%Y-%m-%dT%H:%M:%S")
            if time.time() - time.mktime(stamp) > 45:
                status["lab_online"] = False
        except (ValueError, OverflowError, OSError):
            pass
    return status
