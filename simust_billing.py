"""Paid booking: 20 EUR per 30-minute slot, Stripe Checkout, admin fee waiver."""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

EUR_PER_SLOT = 20
SLOT_MINUTES = 30
CURRENCY = "eur"
PENDING_HOLD_SECONDS = 20 * 60

STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "").strip()
STRIPE_PUBLISHABLE_KEY = os.environ.get("STRIPE_PUBLISHABLE_KEY", "").strip()
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "").strip()
PUBLIC_BASE_URL = (os.environ.get("SIMUST_PUBLIC_BASE_URL") or "").strip().rstrip("/")

_pending_lock = threading.Lock()
_pending: Dict[str, Dict[str, Any]] = {}


def booking_fee_eur(duration_minutes: int) -> int:
    slots = max(1, int(duration_minutes) // SLOT_MINUTES)
    return slots * EUR_PER_SLOT


def booking_fee_cents(duration_minutes: int) -> int:
    return booking_fee_eur(duration_minutes) * 100


def stripe_configured() -> bool:
    return bool(STRIPE_SECRET_KEY)


def public_base_url() -> str:
    if PUBLIC_BASE_URL:
        return PUBLIC_BASE_URL
    return "http://157.180.47.98"


def put_pending(session_id: str, payload: Dict[str, Any]) -> None:
    with _pending_lock:
        _pending[session_id] = dict(payload)
        _pending[session_id]["expires_at"] = time.time() + PENDING_HOLD_SECONDS


def pop_pending(session_id: str) -> Optional[Dict[str, Any]]:
    with _pending_lock:
        item = _pending.pop(session_id, None)
    if not item:
        return None
    if float(item.get("expires_at") or 0) < time.time():
        return None
    return item


def peek_pending(session_id: str) -> Optional[Dict[str, Any]]:
    with _pending_lock:
        item = _pending.get(session_id)
        if not item:
            return None
        if float(item.get("expires_at") or 0) < time.time():
            _pending.pop(session_id, None)
            return None
        return dict(item)


def create_checkout_session(
    *,
    player_id: str,
    player_email: str,
    start_iso: str,
    end_iso: str,
    duration_minutes: int,
    success_url: str,
    cancel_url: str,
) -> Tuple[str, str, int]:
    if not stripe_configured():
        raise RuntimeError("Card payment is not configured on this host")
    try:
        import stripe  # type: ignore
    except ImportError as exc:
        raise RuntimeError("Stripe library is not installed") from exc
    stripe.api_key = STRIPE_SECRET_KEY
    amount = booking_fee_cents(duration_minutes)
    session = stripe.checkout.Session.create(
        mode="payment",
        customer_email=player_email or None,
        success_url=success_url,
        cancel_url=cancel_url,
        line_items=[{
            "quantity": 1,
            "price_data": {
                "currency": CURRENCY,
                "unit_amount": amount,
                "product_data": {
                    "name": "SIMUST training reservation",
                    "description": f"{duration_minutes} minutes ({start_iso} – {end_iso})",
                },
            },
        }],
        metadata={
            "player_id": player_id,
            "start": start_iso,
            "end": end_iso,
            "duration_minutes": str(duration_minutes),
            "amount_eur": str(booking_fee_eur(duration_minutes)),
        },
    )
    if not session.id or not session.url:
        raise RuntimeError("Stripe did not return a checkout URL")
    put_pending(session.id, {
        "player_id": player_id,
        "start": start_iso,
        "end": end_iso,
        "duration_minutes": duration_minutes,
        "amount_eur": booking_fee_eur(duration_minutes),
    })
    return session.id, session.url, booking_fee_eur(duration_minutes)


def retrieve_paid_session(session_id: str) -> Dict[str, Any]:
    if not stripe_configured():
        raise RuntimeError("Card payment is not configured on this host")
    try:
        import stripe  # type: ignore
    except ImportError as exc:
        raise RuntimeError("Stripe library is not installed") from exc
    stripe.api_key = STRIPE_SECRET_KEY
    session = stripe.checkout.Session.retrieve(session_id)
    if str(session.get("payment_status") or "") != "paid":
        raise PermissionError("Payment is not complete")
    meta = dict(session.get("metadata") or {})
    pending = peek_pending(session_id) or {}
    return {
        "session_id": session_id,
        "player_id": meta.get("player_id") or pending.get("player_id") or "",
        "start": meta.get("start") or pending.get("start") or "",
        "end": meta.get("end") or pending.get("end") or "",
        "duration_minutes": int(meta.get("duration_minutes") or pending.get("duration_minutes") or 0),
        "amount_eur": int(meta.get("amount_eur") or pending.get("amount_eur") or 0),
        "email": session.get("customer_details", {}).get("email") if isinstance(session.get("customer_details"), dict) else "",
    }


def verify_webhook(payload: bytes, signature: str) -> Dict[str, Any]:
    if not STRIPE_WEBHOOK_SECRET:
        raise PermissionError("Stripe webhook is not configured")
    try:
        import stripe  # type: ignore
    except ImportError as exc:
        raise RuntimeError("Stripe library is not installed") from exc
    event = stripe.Webhook.construct_event(payload, signature, STRIPE_WEBHOOK_SECRET)
    return event
