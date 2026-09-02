"""AI recovery-decision agent: an optional layer between the deterministic
policy engine (app/engine/policy.py) and playbook execution
(app/engine/actions.py).

Non-negotiable design rule: the policy engine's guardrails ARE the safety
layer and are never touched or second-guessed by this module. This code
can only ever ADD caution to a Decision that policy.decide() already
cleared for execution -- it can turn "proceed" into "hold" or "escalate",
but it can never turn a compliance stop/escalate back into "proceed", it
can never change which playbook is assigned, and it can never do anything
outside the fixed three-action set in app.integrations.llm. If the agent
is disabled, unconfigured, or its response is anything but a clean
recommendation, this is a no-op and the deterministic Decision is used
completely unchanged -- so the system is never less safe with the agent
turned on than with it off, only (at most) more cautious.

Every consultation -- including a "proceed" -- is logged to the audit
trail as its own "ai_recommendation" stage, separate from the
deterministic "decision" stage, so it's always possible to see whether
the agent was consulted for a given signal and what it said.
"""
import json
from datetime import datetime
from typing import Optional

from app import db
from app.config import settings
from app.models import Decision, Diagnosis, Signal, SignalType

ALLOWED_AGENT_ACTIONS = {"proceed", "hold", "escalate"}


def build_context(signal: Signal, diagnosis: Diagnosis, decision: Decision, now_utc: datetime) -> dict:
    """Everything handed to the agent to reason over -- real values read
    from the signal and the audit/state store, nothing invented.

    `current_date` is critical, not decorative: without it, the model has
    no grounded reference point for calendar-relative facts like
    invoice_due_date and falls back to its own training-time sense of
    "now" -- which is wrong for a simulated demo batch (see --simulate-time
    in scripts/run_batch.py) and can make it flag a genuinely overdue
    invoice as "due date is in the future, data error" even though
    detection already verified it's overdue relative to the batch's actual
    simulated time (app/engine/detection.py)."""
    context = {
        "current_date": now_utc.date().isoformat(),
        "signal_type": signal.type.value,
        "amount": signal.amount,
        "currency": signal.currency,
        "root_cause": diagnosis.root_cause.value,
        "diagnosis_confidence": diagnosis.confidence,
        "playbook": decision.playbook,
        "language_pref": signal.language_pref,
        "prior_contact_attempts": db.get_contact_count(signal.customer_id),
    }
    if signal.type == SignalType.SUBSCRIPTION_MANDATE_FAILURE:
        context["mandate_attempt_count"] = signal.metadata.get("attempt_count")
    if signal.type == SignalType.OVERDUE_RECEIVABLE:
        context["invoice_due_date"] = signal.metadata.get("due_date")
    return context


# Backwards-compatible private alias (this was _build_context before the
# prefetch path needed to build a context from outside this module).
_build_context = build_context


def context_fingerprint(context: dict) -> str:
    """Stable identity for a context dict, used to decide whether a
    recommendation fetched ahead of time is still valid for the decision
    actually being made.

    Deliberately fingerprints the WHOLE context rather than a chosen few
    fields: a prefetched answer is speculative (it was fetched before the
    batch mutated contact history, and before any LLM diagnosis refinement),
    so anything at all that differs must force a fresh call rather than
    silently reusing advice given about a different situation."""
    return json.dumps(context, sort_keys=True, default=str)


def refine_decision(
    signal: Signal,
    diagnosis: Diagnosis,
    decision: Decision,
    now_utc: Optional[datetime] = None,
    cache: Optional[dict] = None,
) -> Decision:
    """`cache` is an optional {signal_id: (context_fingerprint, recommendation)}
    map produced by app.engine.pipeline's parallel prefetch. A cached entry is
    used ONLY if its fingerprint matches the context actually built here, so a
    speculative prefetch can never put stale advice behind a real decision --
    on any mismatch this falls through to a normal inline call."""
    if not settings.USE_AI_RECOVERY_AGENT:
        return decision

    # Never consult the agent for a signal the deterministic guardrails
    # already stopped or escalated -- there is nothing left to refine,
    # and a compliance-mandated outcome must never be second-guessed by a
    # model in either direction.
    if decision.stop or decision.escalate:
        return decision

    from app.integrations.llm import llm_recommend_action

    context = build_context(signal, diagnosis, decision, now_utc or datetime.utcnow())

    recommendation = None
    if cache is not None:
        cached = cache.get(signal.id)
        if cached is not None and cached[0] == context_fingerprint(context):
            recommendation = cached[1]
    if recommendation is None:
        recommendation = llm_recommend_action(signal, diagnosis, context)

    if recommendation is None:
        # Agent disabled/unconfigured -- not even attempted, so nothing
        # to log (matches llm_diagnose's convention for USE_LLM_DIAGNOSIS).
        return decision

    db.log_event(signal.id, "ai_recommendation", recommendation.__dict__)

    if recommendation.action not in ALLOWED_AGENT_ACTIONS:
        return decision  # unreachable given llm.py's own validation, kept as defense in depth

    plan = decision.plan + [f"ai_agent:{recommendation.action}"]

    if recommendation.action == "escalate":
        return Decision(
            signal_id=decision.signal_id, playbook=decision.playbook,
            escalate=True, stop=False, stop_reason="ai_flagged_for_review", plan=plan,
        )
    if recommendation.action == "hold":
        return Decision(
            signal_id=decision.signal_id, playbook=decision.playbook,
            escalate=False, stop=True, stop_reason="ai_recommended_hold", plan=plan,
        )

    # "proceed" -- deterministic decision stands; only the plan gets the
    # note that the agent was consulted and agreed.
    return Decision(
        signal_id=decision.signal_id, playbook=decision.playbook,
        escalate=decision.escalate, stop=decision.stop,
        stop_reason=decision.stop_reason, plan=plan,
    )
