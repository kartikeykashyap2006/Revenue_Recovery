import random
from datetime import datetime, timedelta

from app import db
from app.models import Signal, Decision, ActionResult, Channel, ActionStatus
from app.integrations import messaging
from app.playbooks.messaging_templates import receivable_reminder_message

# See app/playbooks/payment_retry.py's RECOVERY_PROBABILITY comment: this
# is an estimate handed to the confirmation step, not a direct outcome.
RECOVERY_PROBABILITY = {
    "no_response": 0.3,
    "cash_flow": 0.2,
    "unknown": 0.15,
}


def run(signal: Signal, decision: Decision) -> ActionResult:
    due_date = signal.metadata.get("due_date", "recently")
    message = receivable_reminder_message(signal, due_date)
    channel = Channel.EMAIL
    messaging.send(channel.value, signal.customer_id, message, signal_id=signal.id)

    reason_code = signal.metadata.get("reason_code", "unknown")
    prob = RECOVERY_PROBABILITY.get(reason_code, 0.15)
    # No payment link exists for a B2B receivable -- key the pending
    # recovery on the invoice itself so a later confirmation event
    # (simulated here; in principle a real reconciliation feed) can be
    # matched back to this signal.
    reference = signal.metadata.get("invoice_id", signal.id)
    db.record_pending_recovery(
        signal_id=signal.id, playbook="receivables_chaser", amount=signal.amount,
        reference=reference, recovery_probability=prob,
    )

    # A promise-to-pay is a real, independently-observed data point (the
    # customer said they'd pay by a date) -- whether that promise is kept
    # is a separate question from whether the invoice is ultimately
    # confirmed paid, so this no longer depends on an immediate "recovered"
    # decision that doesn't exist at send-time anymore.
    promised = False
    if random.random() < 0.3:
        promised_date = (datetime.utcnow() + timedelta(days=7)).date().isoformat()
        db.record_promise_to_pay(signal.id, signal.customer_id, signal.amount, promised_date)
        promised = True

    return ActionResult(
        signal_id=signal.id,
        playbook="receivables_chaser",
        channel=channel,
        status=ActionStatus.SENT,
        message_sent=message,
        amount_recovered=0.0,
        details={"promise_to_pay_recorded": promised, "recovery_confirmation": "pending"},
    )
