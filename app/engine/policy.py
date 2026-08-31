from datetime import datetime, timedelta
from typing import Optional

from app import db
from app.config import settings
from app.models import Signal, SignalType, RootCause, Diagnosis, Decision

IST_OFFSET = timedelta(hours=5, minutes=30)

# Root causes that must never be auto-retried/auto-contacted -- always escalate
# to a human for compliance / risk reasons.
ALWAYS_ESCALATE = {RootCause.BANK_DECLINED_RISK, RootCause.INVOICE_DISPUTE}

# High-value escalation is scoped per signal type: a "high value" card
# payment and a "high value" B2B invoice are different orders of magnitude,
# so a single flat threshold would either never trigger for payments or
# always trigger for receivables. Falls back to settings.HIGH_VALUE_ESCALATION_THRESHOLD
# for any type not listed here.
HIGH_VALUE_THRESHOLD_BY_TYPE = {
    SignalType.PAYMENT_FAILURE: 20000,
    SignalType.CHECKOUT_ABANDONMENT: 30000,
    SignalType.SUBSCRIPTION_MANDATE_FAILURE: 10000,
    SignalType.OVERDUE_RECEIVABLE: 250000,
}

PLAYBOOK_BY_TYPE = {
    SignalType.PAYMENT_FAILURE: "payment_retry",
    SignalType.CHECKOUT_ABANDONMENT: "checkout_dropoff",
    SignalType.SUBSCRIPTION_MANDATE_FAILURE: "subscription_mandate",
    SignalType.OVERDUE_RECEIVABLE: "receivables_chaser",
}


def _in_quiet_hours(now_utc: Optional[datetime] = None) -> bool:
    """Quiet hours are defined in the customer's local time (IST), not
    server/UTC time -- outreach at 2am UTC is 7:30am IST (fine), while
    outreach at 2am IST (20:30 UTC the previous day) is exactly the kind of
    contact these hours exist to prevent. Converts explicitly rather than
    relying on server tz."""
    now_utc = now_utc or datetime.utcnow()
    ist_now = now_utc + IST_OFFSET
    hour = ist_now.hour
    start, end = settings.QUIET_HOURS_START, settings.QUIET_HOURS_END
    if start > end:  # wraps past midnight, e.g. 21 -> 9
        return hour >= start or hour < end
    return start <= hour < end


def decide(signal: Signal, diagnosis: Diagnosis, now_utc: Optional[datetime] = None) -> Decision:
    playbook = PLAYBOOK_BY_TYPE.get(signal.type, "unknown")
    plan = [f"diagnose:{diagnosis.root_cause.value}"]

    # --- Compliance guardrails (checked first, before anything else) ---
    if db.is_opted_out(signal.customer_id):
        return Decision(
            signal_id=signal.id, playbook=playbook, escalate=False, stop=True,
            stop_reason="customer_opted_out", plan=plan,
        )

    if diagnosis.root_cause in ALWAYS_ESCALATE:
        plan.append("escalate:compliance_sensitive_root_cause")
        return Decision(
            signal_id=signal.id, playbook=playbook, escalate=True, stop=True,
            stop_reason="requires_human_review", plan=plan,
        )

    if signal.amount >= HIGH_VALUE_THRESHOLD_BY_TYPE.get(signal.type, settings.HIGH_VALUE_ESCALATION_THRESHOLD):
        plan.append("escalate:high_value")
        return Decision(
            signal_id=signal.id, playbook=playbook, escalate=True, stop=False,
            stop_reason=None, plan=plan,
        )

    # --- Stopping rules ---
    contact_count = db.get_contact_count(signal.customer_id)
    if contact_count >= settings.MAX_CONTACT_ATTEMPTS:
        return Decision(
            signal_id=signal.id, playbook=playbook, escalate=False, stop=True,
            stop_reason="max_contact_attempts_reached", plan=plan,
        )

    last_contact = db.get_last_contact_time(signal.customer_id)
    if last_contact and datetime.utcnow() - last_contact < timedelta(hours=settings.COOLDOWN_HOURS_BETWEEN_ATTEMPTS):
        return Decision(
            signal_id=signal.id, playbook=playbook, escalate=False, stop=True,
            stop_reason="cooldown_active", plan=plan,
        )

    if _in_quiet_hours(now_utc):
        return Decision(
            signal_id=signal.id, playbook=playbook, escalate=False, stop=True,
            stop_reason="quiet_hours", plan=plan,
        )

    plan.append(f"execute:{playbook}")
    return Decision(
        signal_id=signal.id, playbook=playbook, escalate=False, stop=False,
        stop_reason=None, plan=plan,
    )
