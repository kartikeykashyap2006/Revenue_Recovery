"""Thin wrapper around the Razorpay test-mode API.

Falls back to a local mock when RAZORPAY_KEY_ID/SECRET aren't set yet, so
the rest of the engine can be built and demoed before real test-mode keys
are wired up. Once keys are added to .env, real payment links are created
against Razorpay's test-mode sandbox (no real money moves in test mode).
"""
import uuid
from typing import Any, Dict

from app.config import settings
from app.models import Signal

_client = None


def _get_client():
    global _client
    if _client is None:
        import razorpay

        _client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
    return _client


def _has_credentials() -> bool:
    return bool(settings.RAZORPAY_KEY_ID and settings.RAZORPAY_KEY_SECRET)


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
            "contact": signal.metadata.get("phone", "9999999999"),
            "email": signal.metadata.get("email", "test@example.com"),
        },
        "notify": {"sms": True, "email": True},
        "reminder_enable": True,
        "notes": {"signal_id": signal.id, "signal_type": signal.type.value},
    }
    link = client.payment_link.create(payload)
    return {"id": link["id"], "short_url": link["short_url"], "live": True}


def fetch_payment_link_status(link_id: str) -> Dict[str, Any]:
    if not _has_credentials() or link_id.startswith("plink_mock_"):
        return {"status": "unknown", "live": False}
    client = _get_client()
    link = client.payment_link.fetch(link_id)
    return {"status": link.get("status"), "live": True}
