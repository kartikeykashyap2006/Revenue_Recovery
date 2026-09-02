from app import db
from app.models import Signal, Decision, ActionResult, Channel, ActionStatus
from app.integrations import razorpay_client, messaging
from app.playbooks.messaging_templates import payment_retry_message

# Root-cause-aware estimate of how likely this outreach is to result in a
# real payment. This no longer decides the outcome directly -- it's
# handed to app.engine.confirmation, which draws against it in a separate,
# distinctly-audited confirmation step (see that module for why).
RECOVERY_PROBABILITY = {
    "insufficient_funds": 0.35,
    "card_expired": 0.55,
    "network_error": 0.7,
    "wrong_otp": 0.6,
    "exceeded_limit": 0.3,
    "unknown": 0.15,
}


def run(signal: Signal, decision: Decision) -> ActionResult:
    link = razorpay_client.create_recovery_payment_link(signal)
    message = payment_retry_message(signal, link["short_url"])
    channel = Channel.WHATSAPP if signal.language_pref == "hi" else Channel.SMS
    messaging.send(channel.value, signal.customer_id, message, signal_id=signal.id)

    reason_code = signal.metadata.get("reason_code", "unknown")
    prob = RECOVERY_PROBABILITY.get(reason_code, 0.2)
    db.record_pending_recovery(
        signal_id=signal.id, playbook="payment_retry", amount=signal.amount,
        reference=link["id"], recovery_probability=prob,
    )

    return ActionResult(
        signal_id=signal.id,
        playbook="payment_retry",
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
