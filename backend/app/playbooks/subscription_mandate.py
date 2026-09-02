from datetime import datetime
from typing import Optional

from app import db
from app.models import Signal, Decision, ActionResult, Channel, ActionStatus
from app.integrations import razorpay_client, messaging
from app.playbooks.messaging_templates import mandate_retry_message

RECOVERY_PROBABILITY_BY_ATTEMPT = {1: 0.3, 2: 0.25, 3: 0.15}

RECOVERY_PROBABILITY_BY_CAUSE = {
    "insufficient_funds": 0.3,
    "mandate_expired": 0.5,
    "card_expired": 0.5,
    "bank_declined": 0.1,
}


def run(signal: Signal, decision: Decision, now_utc: Optional[datetime] = None) -> ActionResult:
    link = razorpay_client.create_recovery_payment_link(signal)
    message = mandate_retry_message(signal, link["short_url"])
    # The agent may pick the channel (validated against this playbook's own
    # supported list in app/engine/agent.py); otherwise the default applies.
    channel = Channel(decision.channel_override) if decision.channel_override else Channel.WHATSAPP if signal.language_pref == "hi" else Channel.SMS
    messaging.send(channel.value, signal.customer_id, message, signal_id=signal.id)

    attempt = int(signal.metadata.get("attempt_count", 1))
    reason_code = signal.metadata.get("reason_code", "unknown")
    base = RECOVERY_PROBABILITY_BY_CAUSE.get(reason_code, 0.2)
    stage = RECOVERY_PROBABILITY_BY_ATTEMPT.get(min(attempt, 3), 0.1)
    # This estimate is handed to the confirmation step -- see
    # app/playbooks/payment_retry.py's RECOVERY_PROBABILITY comment.
    prob = min(base + stage, 0.85)
    db.record_pending_recovery(
        signal_id=signal.id, playbook="subscription_mandate", amount=signal.amount,
        reference=link["id"], recovery_probability=prob,
    )

    return ActionResult(
        signal_id=signal.id,
        playbook="subscription_mandate",
        channel=channel,
        status=ActionStatus.SENT,
        message_sent=message,
        amount_recovered=0.0,
        details={
            "payment_link": link["short_url"],
            "payment_link_id": link["id"],
            "attempt": attempt,
            "simulated": not link.get("live", False),
            "recovery_confirmation": "pending",
        },
    )
