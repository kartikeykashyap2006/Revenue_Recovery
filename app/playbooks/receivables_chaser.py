import random
from datetime import datetime, timedelta

from app import db
from app.models import Signal, Decision, ActionResult, Channel, ActionStatus
from app.integrations import messaging
from app.playbooks.messaging_templates import receivable_reminder_message

RECOVERY_PROBABILITY = {
    "no_response": 0.3,
    "cash_flow": 0.2,
    "unknown": 0.15,
}


def run(signal: Signal, decision: Decision) -> ActionResult:
    due_date = signal.metadata.get("due_date", "recently")
    message = receivable_reminder_message(signal, due_date)
    channel = Channel.EMAIL
    messaging.send(channel.value, signal.customer_id, message)

    reason_code = signal.metadata.get("reason_code", "unknown")
    prob = RECOVERY_PROBABILITY.get(reason_code, 0.15)
    recovered = random.random() < prob
    amount_recovered = 0.0
    promised = False

    if recovered:
        amount_recovered = signal.amount
        status = ActionStatus.RECOVERED
    elif random.random() < 0.3:
        promised_date = (datetime.utcnow() + timedelta(days=7)).date().isoformat()
        db.record_promise_to_pay(signal.id, signal.customer_id, signal.amount, promised_date)
        status = ActionStatus.SENT
        promised = True
    else:
        status = ActionStatus.SENT

    return ActionResult(
        signal_id=signal.id,
        playbook="receivables_chaser",
        channel=channel,
        status=status,
        message_sent=message,
        amount_recovered=amount_recovered,
        details={"promise_to_pay_recorded": promised},
    )
