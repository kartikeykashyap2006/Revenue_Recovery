from app.models import Signal, Decision, ActionResult, Channel, ActionStatus
from app.playbooks import (
    payment_retry,
    checkout_dropoff,
    subscription_mandate,
    receivables_chaser,
)

PLAYBOOKS = {
    "payment_retry": payment_retry.run,
    "checkout_dropoff": checkout_dropoff.run,
    "subscription_mandate": subscription_mandate.run,
    "receivables_chaser": receivables_chaser.run,
}


def execute(signal: Signal, decision: Decision) -> ActionResult:
    if decision.stop:
        return ActionResult(
            signal_id=signal.id, playbook=decision.playbook, channel=Channel.NONE,
            status=ActionStatus.STOPPED, message_sent=None, amount_recovered=0.0,
            details={"reason": decision.stop_reason},
        )
    if decision.escalate:
        return ActionResult(
            signal_id=signal.id, playbook=decision.playbook, channel=Channel.NONE,
            status=ActionStatus.ESCALATED, message_sent=None, amount_recovered=0.0,
            details={"reason": "flagged_for_human_review"},
        )

    handler = PLAYBOOKS.get(decision.playbook)
    if handler is None:
        return ActionResult(
            signal_id=signal.id, playbook=decision.playbook, channel=Channel.NONE,
            status=ActionStatus.SKIPPED, message_sent=None, amount_recovered=0.0,
            details={"reason": "no_playbook_registered"},
        )
    return handler(signal, decision)
