from datetime import datetime, timedelta
from typing import Optional

from app import db
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


def execute(signal: Signal, decision: Decision, now_utc: Optional[datetime] = None) -> ActionResult:
    # Escalation takes precedence over a plain stop. A compliance-sensitive
    # root cause (see policy.ALWAYS_ESCALATE) sets BOTH escalate=True and
    # stop=True, and must surface as ESCALATED (flagged for human review) --
    # not STOPPED, which is reserved for opt-outs/cooldown/quiet-hours/
    # max-attempts (none of which ever set escalate=True). Checking `stop`
    # first here previously swallowed every compliance escalation into an
    # indistinguishable STOPPED result, so `escalated_count` in reporting
    # never counted them and the audit trail understated real escalations.
    if decision.escalate:
        return ActionResult(
            signal_id=signal.id, playbook=decision.playbook, channel=Channel.NONE,
            status=ActionStatus.ESCALATED, message_sent=None, amount_recovered=0.0,
            details={"reason": decision.stop_reason or "flagged_for_human_review"},
        )
    if decision.stop:
        return ActionResult(
            signal_id=signal.id, playbook=decision.playbook, channel=Channel.NONE,
            status=ActionStatus.STOPPED, message_sent=None, amount_recovered=0.0,
            details={"reason": decision.stop_reason},
        )

    # The agent asked to wait. Persist the whole signal so a LATER batch
    # genuinely picks it up once the wait has elapsed, and put it through
    # every guardrail again at that point -- deferral postpones contact, it
    # never pre-authorises it. Recording a deferral without that follow-up
    # would be a promise the system doesn't keep.
    if decision.defer_hours > 0:
        reference_now = now_utc or datetime.utcnow()
        not_before = reference_now + timedelta(hours=decision.defer_hours)
        signal_dict = {**signal.__dict__, "type": signal.type.value}
        db.record_deferred_signal(
            signal_dict,
            not_before=not_before.isoformat(),
            reason=f"ai_agent_deferred_{decision.defer_hours}h",
        )
        return ActionResult(
            signal_id=signal.id, playbook=decision.playbook, channel=Channel.NONE,
            status=ActionStatus.DEFERRED, message_sent=None, amount_recovered=0.0,
            details={
                "reason": "ai_agent_requested_delay",
                "defer_hours": decision.defer_hours,
                "not_before": not_before.isoformat(),
            },
        )

    handler = PLAYBOOKS.get(decision.playbook)
    if handler is None:
        return ActionResult(
            signal_id=signal.id, playbook=decision.playbook, channel=Channel.NONE,
            status=ActionStatus.SKIPPED, message_sent=None, amount_recovered=0.0,
            details={"reason": "no_playbook_registered"},
        )

    # A playbook failure (e.g. Razorpay API hiccup, messaging provider
    # outage) must never take down the rest of the batch -- it becomes a
    # FAILED result for that one signal, fully logged, and processing
    # continues for everyone else.
    try:
        return handler(signal, decision)
    except Exception as exc:
        return ActionResult(
            signal_id=signal.id, playbook=decision.playbook, channel=Channel.NONE,
            status=ActionStatus.FAILED, message_sent=None, amount_recovered=0.0,
            details={"error": str(exc), "error_type": type(exc).__name__},
        )
