"""Turns a raw event stream (app.data.raw_events.RawEvent) into Signal
objects the rest of the pipeline already knows how to handle.

This is the actual "detection" step the rest of the engine was missing:
group raw events by case, check whether a resolving event ever showed up
for that case, and only emit a Signal when the case genuinely represents
revenue at risk. A case that resolved on its own (customer retried and it
went through, they came back and paid, the invoice got settled) produces
no signal at all -- that's the difference between this and just
relabeling pre-sorted data.

Signal.metadata is populated with exactly the keys diagnosis.py and the
playbooks already expect (reason_code, due_date, invoice_id,
attempt_count, phone, email) so nothing downstream needs to change --
detection only changes where a Signal comes from, not what one looks
like once it exists.
"""
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional

from app.data.raw_events import RawEvent
from app.models import Signal, SignalType

# Which event type resolves an in-flight case for each scenario -- if one
# of these shows up for a case_id, the case is fine and produces no signal.
_RESOLVING_EVENTS = {
    "payment.failed": "payment.captured",
    "checkout.session.started": "payment.captured",
    "subscription.charge.failed": "subscription.charge.succeeded",
    "invoice.created": "invoice.paid",
}

# Which "trigger" event type (the one that opens a case) maps to which
# signal category.
_TRIGGER_TO_SIGNAL_TYPE = {
    "payment.failed": SignalType.PAYMENT_FAILURE,
    "checkout.session.started": SignalType.CHECKOUT_ABANDONMENT,
    "subscription.charge.failed": SignalType.SUBSCRIPTION_MANDATE_FAILURE,
    "invoice.created": SignalType.OVERDUE_RECEIVABLE,
}


def _build_signal(case_id: str, trigger_type: str, events: List[RawEvent]) -> Optional[Signal]:
    signal_type = _TRIGGER_TO_SIGNAL_TYPE[trigger_type]
    trigger_events = [e for e in events if e.event_type == trigger_type]
    latest = trigger_events[-1]
    metadata = {"phone": latest.payload.get("phone"), "email": latest.payload.get("email")}

    if signal_type == SignalType.PAYMENT_FAILURE:
        metadata["reason_code"] = latest.payload.get("error_code")
        metadata["payment_method"] = latest.payload.get("payment_method")
    elif signal_type == SignalType.CHECKOUT_ABANDONMENT:
        metadata["reason_code"] = latest.payload.get("friction_hint")
        metadata["checkout_id"] = case_id
    elif signal_type == SignalType.SUBSCRIPTION_MANDATE_FAILURE:
        # attempt_count is the real count of failed-charge events observed
        # for this case, not an arbitrary random draw.
        metadata["reason_code"] = latest.payload.get("error_code")
        metadata["attempt_count"] = len(trigger_events)
    else:  # OVERDUE_RECEIVABLE
        metadata["reason_code"] = latest.payload.get("status_hint")
        metadata["due_date"] = latest.payload.get("due_date")
        metadata["invoice_id"] = latest.payload.get("invoice_id", case_id)

    return Signal(
        type=signal_type,
        customer_id=latest.customer_id,
        customer_name=latest.customer_name,
        amount=latest.amount,
        currency=latest.currency,
        language_pref=latest.payload.get("language_pref", "en"),
        metadata=metadata,
    )


def detect_signals(events: List[RawEvent], now_utc: Optional[datetime] = None) -> List[Signal]:
    """Groups a raw, unlabeled event stream by case_id and emits a Signal
    for every case that has NOT resolved on its own -- i.e. a trigger
    event (payment.failed, checkout.session.started,
    subscription.charge.failed, invoice.created) exists with no matching
    resolving event (payment.captured, subscription.charge.succeeded,
    invoice.paid) anywhere in that case's events.

    For OVERDUE_RECEIVABLE specifically, an unresolved invoice only
    becomes a signal once its due_date has actually passed relative to
    now_utc -- an invoice that isn't overdue yet correctly produces no
    signal regardless of whether it's been paid."""
    now_utc = now_utc or datetime.utcnow()

    by_case: Dict[str, List[RawEvent]] = defaultdict(list)
    for e in events:
        by_case[e.case_id].append(e)

    signals: List[Signal] = []
    for case_id, case_events in by_case.items():
        types_present = {e.event_type for e in case_events}
        trigger_type = next((t for t in _TRIGGER_TO_SIGNAL_TYPE if t in types_present), None)
        if trigger_type is None:
            continue  # a resolving event with no trigger of its own -- nothing to detect

        resolving_type = _RESOLVING_EVENTS[trigger_type]
        if resolving_type in types_present:
            continue  # case resolved on its own -- correctly no signal

        if trigger_type == "invoice.created":
            due_date_str = case_events[0].payload.get("due_date")
            due_date = datetime.fromisoformat(due_date_str) if due_date_str else now_utc
            if due_date > now_utc:
                continue  # not overdue yet -- correctly no signal

        signal = _build_signal(case_id, trigger_type, case_events)
        if signal is not None:
            signals.append(signal)

    return signals
