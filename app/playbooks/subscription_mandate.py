import random

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


def run(signal: Signal, decision: Decision) -> ActionResult:
    link = razorpay_client.create_recovery_payment_link(signal)
    message = mandate_retry_message(signal, link["short_url"])
    channel = Channel.WHATSAPP if signal.language_pref == "hi" else Channel.SMS
    messaging.send(channel.value, signal.customer_id, message)

    attempt = int(signal.metadata.get("attempt_count", 1))
    reason_code = signal.metadata.get("reason_code", "unknown")
    base = RECOVERY_PROBABILITY_BY_CAUSE.get(reason_code, 0.2)
    stage = RECOVERY_PROBABILITY_BY_ATTEMPT.get(min(attempt, 3), 0.1)
    prob = min(base + stage, 0.85)
    recovered = random.random() < prob
    amount_recovered = signal.amount if recovered else 0.0

    return ActionResult(
        signal_id=signal.id,
        playbook="subscription_mandate",
        channel=channel,
        status=ActionStatus.RECOVERED if recovered else ActionStatus.SENT,
        message_sent=message,
        amount_recovered=amount_recovered,
        details={"payment_link": link["short_url"], "attempt": attempt, "simulated": not link.get("live", False)},
    )
