"""Thin wrapper around the Razorpay test-mode API.

Falls back to a local mock when RAZORPAY_KEY_ID/SECRET aren't set yet, so
the rest of the engine can be built and demoed before real test-mode keys
are wired up. Once keys are added to .env, real payment links are created
against Razorpay's test-mode sandbox (no real money moves in test mode).
"""
import time
import uuid
from typing import Any, Dict

from app.config import settings
from app.models import Signal

_client = None
_last_call_at = 0.0

# Razorpay's test-mode API enforces a per-second rate limit that a tight
# batch loop (dozens of signals processed back-to-back) will exceed almost
# immediately -- this showed up as "Too many requests" BadRequestErrors on
# most calls in a real run. A minimum interval between calls plus a
# retry-with-backoff on exactly that error keeps a real batch resilient
# without silently masking genuine bad-request errors (wrong amount,
# invalid customer fields, etc), which still raise immediately.
MIN_REQUEST_INTERVAL_SECONDS = 1.1
MAX_RATE_LIMIT_RETRIES = 4


def _get_client():
    global _client
    if _client is None:
        import razorpay

        _client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
    return _client


def _has_credentials() -> bool:
    return bool(settings.RAZORPAY_KEY_ID and settings.RAZORPAY_KEY_SECRET)


def _throttle() -> None:
    global _last_call_at
    elapsed = time.monotonic() - _last_call_at
    if elapsed < MIN_REQUEST_INTERVAL_SECONDS:
        time.sleep(MIN_REQUEST_INTERVAL_SECONDS - elapsed)
    _last_call_at = time.monotonic()


def _call_with_rate_limit_retry(fn):
    import razorpay

    for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
        _throttle()
        try:
            return fn()
        except razorpay.errors.BadRequestError as exc:
            is_rate_limit = "too many requests" in str(exc).lower()
            if not is_rate_limit or attempt == MAX_RATE_LIMIT_RETRIES:
                raise
            backoff = MIN_REQUEST_INTERVAL_SECONDS * (2 ** attempt)
            time.sleep(backoff)


def create_recovery_payment_link(signal: Signal) -> Dict[str, Any]:
    """Create a payment link for the customer to complete/retry payment.
    Returns a dict with at least `short_url` and `live` (bool)."""
    if not _has_credentials():
        fake_id = uuid.uuid4().hex[:10]
        return {
            "id": f"plink_mock_{fake_id}",
            "short_url": f"https://rzp.io/mock/{fake_id}",
            "live": False,
        }

    client = _get_client()
    payload = {
        "amount": int(round(signal.amount * 100)),  # paise
        "currency": signal.currency,
        "description": f"Recovery payment for {signal.type.value} ({signal.id})",
        "customer": {
            "name": signal.customer_name,
            "contact": signal.metadata.get("phone", "9123456780"),
            "email": signal.metadata.get("email", "test@example.com"),
        },
        "notify": {"sms": True, "email": True},
        "reminder_enable": True,
        "notes": {"signal_id": signal.id, "signal_type": signal.type.value},
    }
    link = _call_with_rate_limit_retry(lambda: client.payment_link.create(payload))
    return {"id": link["id"], "short_url": link["short_url"], "live": True}


def fetch_payment_link_status(link_id: str) -> Dict[str, Any]:
    if not _has_credentials() or link_id.startswith("plink_mock_"):
        return {"status": "unknown", "live": False}
    client = _get_client()
    link = _call_with_rate_limit_retry(lambda: client.payment_link.fetch(link_id))
    return {"status": link.get("status"), "live": True}
