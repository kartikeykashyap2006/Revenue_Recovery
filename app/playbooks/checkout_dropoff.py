from app import db
from app.models import Signal, Decision, ActionResult, Channel, ActionStatus
from app.integrations import razorpay_client, messaging
from app.playbooks.messaging_templates import checkout_reminder_message

# See app/playbooks/payment_retry.py's RECOVERY_PROBABILITY comment: this
# is an estimate handed to the confirmation step, not a direct outcome.
RECOVERY_PROBABILITY = {
    "price_page_exit": 0.2,
    "no_upi_available": 0.45,
    "checkout_error": 0.6,
    "session_timeout": 0.4,
    "unknown": 0.15,
}


def run(signal: Signal, decision: Decision) -> ActionResult:
    link = razorpay_client.create_recovery_payment_link(signal)
    message = checkout_reminder_message(signal, link["short_url"])
    channel = Channel.WHATSAPP if signal.language_pref == "hi" else Channel.EMAIL
    messaging.send(channel.value, signal.customer_id, message, signal_id=signal.id)

    reason_code = signal.metadata.get("reason_code", "unknown")
    prob = RECOVERY_PROBABILITY.get(reason_code, 0.15)
    db.record_pending_recovery(
        signal_id=signal.id, playbook="checkout_dropoff", amount=signal.amount,
        reference=link["id"], recovery_probability=prob,
    )

    return ActionResult(
        signal_id=signal.id,
        playbook="checkout_dropoff",
        channel=channel,
        status=ActionStatus.SENT,
        message_sent=message,
        amount_recovered=0.0,
        details={
            "payment_link": link["short_url"],
            "payment_link_id": link["id"],
            "simulated": not link.get("live", False),
            "recovery_confirmation": "pending",
        },
    )
