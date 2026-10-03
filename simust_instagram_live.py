"""Push Field A camera 1 to an Instagram live during a test.

Credentials come from lab.env (INSTAGRAM_USERNAME / INSTAGRAM_PASSWORD).
They are never written into source or sent to the public site.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Field A, camera 1 (192.168.2.1). Override with INSTAGRAM_CAMERA_URL.
DEFAULT_CAMERA_URL = "rtsp://admin:majidAram2@192.168.2.1:554/Streaming/Channels/101/"
_HERE = os.path.dirname(os.path.abspath(__file__))
_SESSION_PATH = os.path.join(_HERE, "instagram_session.json")
_LOCK = threading.Lock()
_proc: Optional[subprocess.Popen] = None
_broadcast_id = ""
_last_error = ""


def status() -> Dict[str, Any]:
    running = _proc is not None and _proc.poll() is None
    return {
        "on": running,
        "broadcast_id": _broadcast_id if running else "",
        "camera": "camera-1",
        "field": "A",
        "error": "" if running else _last_error,
    }


def _camera_url() -> str:
    return (os.environ.get("INSTAGRAM_CAMERA_URL") or DEFAULT_CAMERA_URL).strip()


def _credentials() -> tuple:
    user = (os.environ.get("INSTAGRAM_USERNAME") or "").strip()
    password = os.environ.get("INSTAGRAM_PASSWORD") or ""
    if not user or not password:
        raise RuntimeError(
            "Set INSTAGRAM_USERNAME and INSTAGRAM_PASSWORD in lab.env, then restart app.py"
        )
    return user, password


def _ffmpeg_bin() -> str:
    for path in (
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
        r"C:\ffmpeg\bin\ffmpeg.exe",
        "ffmpeg",
    ):
        try:
            subprocess.run([path, "-version"], capture_output=True, timeout=5)
            return path
        except Exception:
            continue
    raise RuntimeError("ffmpeg was not found")


def _saved_session_user(path: str) -> str:
    """Username stored in the last Instagram session, if the file can be read."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle) or {}
    except Exception:
        return ""
    if not isinstance(data, dict):
        return ""
    auth = data.get("authorization_data") or {}
    if isinstance(auth, dict) and auth.get("username"):
        return str(auth.get("username") or "").strip()
    return str(data.get("username") or "").strip()


def _drop_session_file():
    if os.path.isfile(_SESSION_PATH):
        try:
            os.remove(_SESSION_PATH)
        except OSError:
            pass


def _login():
    try:
        from instagrapi import Client
    except ImportError as exc:
        raise RuntimeError("instagrapi is not installed on the lab PC") from exc
    user, password = _credentials()
    client = Client()
    client.delay_range = [1, 2]
    saved = _saved_session_user(_SESSION_PATH) if os.path.isfile(_SESSION_PATH) else ""
    if saved and saved.lower() != user.lower():
        logger.info("Instagram session is for %s; signing in as %s", saved, user)
        _drop_session_file()
        saved = ""
    if saved:
        try:
            client.load_settings(_SESSION_PATH)
        except Exception:
            logger.info("Instagram session file could not be loaded; signing in again")
            _drop_session_file()
    try:
        client.login(user, password)
    except Exception as exc:
        name = type(exc).__name__
        _drop_session_file()
        if "Challenge" in name or "TwoFactor" in name:
            raise RuntimeError(
                "Instagram asked to confirm the login for "
                + user
                + ". Approve it in the Instagram app, then press Insta again."
            ) from exc
        if "Suspended" in name:
            raise RuntimeError(
                user
                + " is suspended on Instagram. "
                "Set INSTAGRAM_USERNAME and INSTAGRAM_PASSWORD in lab.env to a different account, "
                "restart app.py, then press Insta again."
            ) from exc
        raise RuntimeError("Instagram login failed: " + name) from exc
    try:
        client.dump_settings(_SESSION_PATH)
    except Exception:
        logger.info("Could not save the Instagram session file")
    return client


_NOT_ELIGIBLE = (
    "Instagram will not go live on this account. "
    "It must be a public account, old enough for Live, and have at least 1,000 followers. "
    "Sign in with an account that already qualifies, then press Insta again."
)


def explain_instagram_failure(payload: Any) -> str:
    """Turn Instagram's live refusal into one sentence for the operator."""
    text = ""
    reasons = []
    if isinstance(payload, dict):
        text = str(payload.get("message") or "")
        raw_reasons = payload.get("block_reason") or []
        if isinstance(raw_reasons, list):
            reasons = [str(item) for item in raw_reasons]
    else:
        text = str(payload or "")
    blob = " ".join([text, *reasons])
    if (
        "ACCOUNT_AGE_LIMIT" in blob
        or "NOT_PASS_FOLLOWER_COUNT_CHECK" in blob
        or "not eligible" in blob.lower()
    ):
        return _NOT_ELIGIBLE
    if text and text != "None":
        return "Instagram refused the live: " + text
    return "Instagram did not start a live broadcast"


def _create_broadcast(client) -> Dict[str, Any]:
    data = {
        "_uuid": client.uuid,
        "preview_width": 1280,
        "preview_height": 720,
        "broadcast_message": "SIMUST Field A",
        "broadcast_type": "RTMP",
        "internal_only": 0,
    }
    try:
        result = client.private_request("live/create/", data, with_signature=False)
    except Exception as exc:
        raise RuntimeError(explain_instagram_failure(str(exc))) from exc
    if not isinstance(result, dict) or result.get("status") == "fail" or not result.get("broadcast_id"):
        raise RuntimeError(explain_instagram_failure(result if isinstance(result, dict) else ""))
    return result


def _upload_url(result: Dict[str, Any]) -> str:
    for key in ("upload_url", "rtmp_url", "stream_url"):
        value = result.get(key)
        if isinstance(value, str) and value.startswith("rtmp"):
            return value
    broadcast_id = str(result.get("broadcast_id") or "")
    if not broadcast_id:
        raise RuntimeError("Instagram did not return a stream address")
    return "rtmps://live-upload.instagram.com:443/rtmp/" + broadcast_id


def _start_ffmpeg(upload_url: str) -> subprocess.Popen:
    cmd = [
        _ffmpeg_bin(),
        "-hide_banner",
        "-loglevel",
        "warning",
        "-rtsp_transport",
        "tcp",
        "-i",
        _camera_url(),
        "-f",
        "lavfi",
        "-i",
        "anullsrc=r=44100:cl=stereo",
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-tune",
        "zerolatency",
        "-pix_fmt",
        "yuv420p",
        "-r",
        "30",
        "-g",
        "60",
        "-b:v",
        "2800k",
        "-maxrate",
        "2800k",
        "-bufsize",
        "5600k",
        "-vf",
        "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-ar",
        "44100",
        "-f",
        "flv",
        upload_url,
    ]
    return subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )


def _end_broadcast(broadcast_id: str) -> None:
    if not broadcast_id:
        return
    try:
        client = _login()
        client.private_request(
            f"live/{broadcast_id}/end_broadcast/",
            {"_uuid": client.uuid},
            with_signature=False,
        )
    except Exception as exc:
        logger.warning("Could not end Instagram live %s: %s", broadcast_id, type(exc).__name__)


def _stop_process() -> str:
    global _proc, _broadcast_id
    proc = _proc
    broadcast_id = _broadcast_id
    _proc = None
    _broadcast_id = ""
    if proc is not None and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
    return broadcast_id


def stop_live() -> Dict[str, Any]:
    global _last_error
    with _LOCK:
        broadcast_id = _stop_process()
        _last_error = ""
    if broadcast_id:
        _end_broadcast(broadcast_id)
    return status()


def start_live() -> Dict[str, Any]:
    """Sign in and push camera 1. Caller must already know a test is running."""
    global _proc, _broadcast_id, _last_error
    with _LOCK:
        if _proc is not None and _proc.poll() is None:
            return status()
        _last_error = ""
        broadcast_id = ""
        try:
            client = _login()
            created = _create_broadcast(client)
            broadcast_id = str(created.get("broadcast_id") or "")
            upload_url = _upload_url(created)
            proc = _start_ffmpeg(upload_url)
            time.sleep(2.0)
            if proc.poll() is not None:
                err = ""
                if proc.stderr is not None:
                    err = proc.stderr.read().decode("utf-8", errors="replace")[-400:]
                raise RuntimeError(err or "ffmpeg exited before the live started")
            _proc = proc
            _broadcast_id = broadcast_id
            client.private_request(
                f"live/{broadcast_id}/start/",
                {"_uuid": client.uuid, "should_send_notifications": 1},
                with_signature=False,
            )
            logger.info("Instagram live started for Field A camera 1")
            return status()
        except Exception as exc:
            _last_error = str(exc)
            ended = _stop_process() or broadcast_id
            logger.warning("Instagram live failed: %s", _last_error)
            if ended:
                _end_broadcast(ended)
            raise
