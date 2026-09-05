"""Public-host security guards for My SIMUST.

Lab PC (SIMUST_PUBLIC_MODE unset): existing LAN APIs stay open for the operator UI.
Public host (SIMUST_PUBLIC_MODE=1): require a login token, lock lab-only routes,
rate-limit auth, and scope player data to the signed-in user.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import threading
import time
from typing import Any, Dict, Optional, Tuple

from fastapi import HTTPException, Request

PUBLIC_MODE = os.environ.get("SIMUST_PUBLIC_MODE", "").strip().lower() in ("1", "true", "yes")
_SESSION_SECRET_RAW = os.environ.get("SIMUST_SESSION_SECRET", "").strip()
if PUBLIC_MODE and (not _SESSION_SECRET_RAW or _SESSION_SECRET_RAW == "change-me"):
    raise RuntimeError("SIMUST_SESSION_SECRET must be set to a strong value on the public host")
SESSION_SECRET = _SESSION_SECRET_RAW or secrets.token_hex(32)
SESSION_HOURS = int(os.environ.get("SIMUST_SESSION_HOURS", "12"))
PBKDF2_ROUNDS = 260000
PLAYER_ID_RE = __import__("re").compile(r"^[A-Za-z0-9._-]{1,64}$")
PUBLIC_REGISTER_ROLES = {"player", "coach", "manager"}
TRUSTED_PROXY_HOSTS = {"127.0.0.1", "::1", "localhost"}

# Login / register: 8 tries per IP per 10 minutes
_AUTH_WINDOW_S = 600
_AUTH_MAX = 8
_auth_hits: Dict[str, list] = {}
_auth_lock = threading.Lock()

LAB_ONLY_PREFIXES = (
    "/cameras",
    "/check-status",
    "/selections",
    "/start",
    "/stop",
    "/set-simust-speed",
    "/get-simust-speed",
    "/get-levels",
    "/playback-status",
    "/start-realtime",
    "/stop-realtime",
    "/pause-realtime",
    "/set-visualization",
    "/set-simulation",
    "/results",
    "/video-results",
    "/realtime-results",
    "/save-results-to-json",
    "/capture-frame",
    "/create-video-results",
    "/create-results-video",
    "/save-session-to-player",
    "/sync-live-to-host",
    "/sync-accounts-to-host",
    "/sync-reports-to-host",
    "/lab-upsert-player",
    "/unlock-level",
    "/lock-level",
    "/stitch",
    "/open-directory",
    "/create-pdf-report",
    "/delete-player-report",
    "/stop-realtime-camera",
)


def cors_origins() -> list:
    raw = os.environ.get("SIMUST_PUBLIC_ORIGINS", "").strip()
    if raw:
        return [part.strip() for part in raw.split(",") if part.strip()]
    if PUBLIC_MODE:
        return ["https://simust.com", "https://www.simust.com", "https://my.simust.com"]
    return ["*"]


def client_ip(request: Request) -> str:
    peer = request.client.host if request.client else "unknown"
    if peer in TRUSTED_PROXY_HOSTS:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip() or peer
    return peer


def require_player_id(player_id: str) -> str:
    value = (player_id or "").strip()
    if not PLAYER_ID_RE.match(value):
        raise HTTPException(400, "Invalid player id")
    return value


def contained_player_dir(reports_root: str, player_id: str) -> str:
    safe_id = require_player_id(player_id)
    root = os.path.realpath(reports_root)
    player_dir = os.path.realpath(os.path.join(root, safe_id))
    if player_dir != root and not player_dir.startswith(root + os.sep):
        raise HTTPException(400, "Invalid player id")
    return player_dir


def sanitize_profile_image(image: str) -> str:
    value = (image or "").strip()
    if not value:
        return ""
    if PUBLIC_MODE:
        if value.startswith("data:"):
            return ""
        if not (value.startswith("https://") and " " not in value and '"' not in value):
            return ""
        return value[:400]
    return value[:400]


def public_security_headers() -> Dict[str, str]:
    return {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
        "Content-Security-Policy": (
            "default-src 'self'; "
            "img-src 'self' data: https:; "
            "style-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://cdn.jsdelivr.net https://fonts.googleapis.com; "
            "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://cdn.jsdelivr.net https://unpkg.com; "
            "font-src 'self' https://fonts.gstatic.com data:; "
            "connect-src 'self' https://api.stripe.com; "
            "frame-src https://js.stripe.com https://hooks.stripe.com; "
            "base-uri 'self'; form-action 'self' https://checkout.stripe.com"
        ),
    }


def check_auth_rate(request: Request) -> None:
    ip = client_ip(request)
    now = time.time()
    with _auth_lock:
        hits = [t for t in _auth_hits.get(ip, []) if now - t < _AUTH_WINDOW_S]
        if len(hits) >= _AUTH_MAX:
            _auth_hits[ip] = hits
            raise HTTPException(429, "Too many sign-in attempts. Wait a few minutes.")
        hits.append(now)
        _auth_hits[ip] = hits


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("ascii"), PBKDF2_ROUNDS).hex()
    return f"pbkdf2${PBKDF2_ROUNDS}${salt}${digest}"


def verify_password(password: str, stored: str) -> Tuple[bool, Optional[str]]:
    """Return (ok, upgraded_hash_or_None). Upgrades legacy MD5 hashes on success."""
    stored = stored or ""
    if stored.startswith("pbkdf2$"):
        try:
            _, rounds_s, salt, digest = stored.split("$", 3)
            rounds = int(rounds_s)
        except ValueError:
            return False, None
        check = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("ascii"), rounds).hex()
        if hmac.compare_digest(check, digest):
            return True, None
        return False, None
    legacy = hashlib.md5(password.encode("utf-8")).hexdigest()
    if len(stored) == 32 and hmac.compare_digest(legacy, stored):
        return True, hash_password(password)
    if stored and stored.encode("utf-8") == password.encode("utf-8"):
        return True, hash_password(password)
    return False, None


def issue_token(username: str, role: str) -> str:
    exp = int(time.time()) + SESSION_HOURS * 3600
    payload = f"{username}|{role}|{exp}"
    sig = hmac.new(SESSION_SECRET.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}|{sig}"


def parse_token(token: str) -> Dict[str, str]:
    token = (token or "").strip()
    parts = token.split("|")
    if len(parts) != 4:
        raise HTTPException(401, "Sign in required")
    username, role, exp_s, sig = parts
    payload = f"{username}|{role}|{exp_s}"
    expect = hmac.new(SESSION_SECRET.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expect, sig):
        raise HTTPException(401, "Sign in required")
    try:
        exp = int(exp_s)
    except ValueError:
        raise HTTPException(401, "Sign in required")
    if exp < int(time.time()):
        raise HTTPException(401, "Session expired. Sign in again.")
    return {"username": username, "role": role}


def token_from_request(request: Request) -> Optional[str]:
    header = request.headers.get("authorization") or request.headers.get("Authorization") or ""
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return None


def current_user(request: Request, users: Dict[str, Any], required: bool = False) -> Optional[Dict[str, Any]]:
    token = token_from_request(request)
    if not token:
        if required or PUBLIC_MODE:
            raise HTTPException(401, "Sign in required")
        return None
    ident = parse_token(token)
    record = users.get(ident["username"])
    if not record:
        raise HTTPException(401, "Sign in required")
    return {
        "username": ident["username"],
        "role": record.get("role") or ident["role"],
        "club": record.get("club", ""),
        "team": record.get("team", ""),
        "name": record.get("name", ""),
        "surname": record.get("surname", ""),
        "progress": record.get("progress", {}),
    }


def can_access_player(viewer: Optional[Dict[str, Any]], player_id: str, player_meta: Optional[Dict[str, Any]] = None) -> bool:
    if not PUBLIC_MODE and viewer is None:
        return True
    if not viewer:
        return False
    role = viewer.get("role") or "player"
    if role == "player":
        return viewer["username"] == player_id
    meta = player_meta or {}
    if role == "coach":
        return bool(viewer.get("team")) and meta.get("team") == viewer.get("team")
    if role == "manager":
        return bool(viewer.get("club")) and meta.get("club") == viewer.get("club")
    if role == "admin":
        return True
    return False


def is_lab_only_path(path: str) -> bool:
    return any(path == prefix or path.startswith(prefix + "/") or path.startswith(prefix + "-") for prefix in LAB_ONLY_PREFIXES)


def public_user_view(username: str, user: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": username,
        "name": user.get("name", username),
        "surname": user.get("surname", ""),
        "playerId": username,
        "club": user.get("club", ""),
        "team": user.get("team", ""),
        "age": user.get("age", ""),
        "gender": user.get("gender", ""),
        "progress": user.get("progress", {}),
        "role": user.get("role", "player"),
    }
