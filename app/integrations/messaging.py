"""Simulated outbound messaging channel (SMS / WhatsApp / Email).

Razorpay's own APIs don't send arbitrary customer messages, so this stands
in for whatever messaging provider a real merchant would plug in (Twilio,
WhatsApp Business API, an email provider). Every send is logged to the
audit trail so the full recovery workflow -- including "what did we say
and when" -- stays inspectable."""
from app import db


def send(channel: str, to: str, message: str) -> bool:
    db.log_event(to, f"message_sent:{channel}", {"to": to, "message": message})
    return True
