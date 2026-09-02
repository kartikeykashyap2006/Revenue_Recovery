"""Simulated outbound messaging channel (SMS / WhatsApp / Email).

Razorpay's own APIs don't send arbitrary customer messages, so this stands
in for whatever messaging provider a real merchant would plug in (Twilio,
WhatsApp Business API, an email provider). Every send is logged to the
audit trail so the full recovery workflow -- including "what did we say
and when" -- stays inspectable."""
from app import db


def send(channel: str, to: str, message: str, signal_id: str) -> bool:
    """`signal_id` is required, and is what the event is filed under in the
    audit trail -- NOT `to` (the customer id). Filing it under the customer
    id previously broke the single most important demo path: fetching one
    signal's full trace (scripts/inspect_audit.py --signal-id ...) showed
    diagnosis -> decision -> action -> confirmation but silently omitted the
    outreach message itself, because that one event was stored under a
    different key than every other stage of the same signal."""
    db.log_event(signal_id, f"message_sent:{channel}", {"to": to, "message": message})
    return True
