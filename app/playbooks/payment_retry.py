import random

from app.models import Signal, Decision, ActionResult, Channel, ActionStatus
from app.integrations import razorpay_client, messaging
from app.playbooks.messaging_templates import payment_retry_message

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
    messaging.send(channel.value, signal.customer_id, message)

    reason_code = signal.metadata.get("reason_code", "unknown")
    prob = RECOVERY_PROBABILITY.get(reason_code, 0.2)
    recovered = random.random() < prob
    amount_recovered = signal.amount if recovered else 0.0

    return ActionResult(
        signal_id=signal.id,
        playbook="payment_retry",
        channel=channel,
        status=ActionStatus.RECOVERED if recovered else ActionStatus.SENT,
        message_sent=message,
        amount_recovered=amount_recovered,
        details={"payment_link": link["short_url"], "simulated": not link.get("live", False)},
    )
