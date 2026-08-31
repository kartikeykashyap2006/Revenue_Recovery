from datetime import datetime

from app import db
from app.engine.policy import decide, _in_quiet_hours
from app.models import Signal, SignalType, RootCause, Diagnosis


def _signal(stype=SignalType.PAYMENT_FAILURE, amount=1000, customer_id="c1"):
    return Signal(type=stype, customer_id=customer_id, customer_name="Test", amount=amount)


def _diag(root_cause=RootCause.INSUFFICIENT_FUNDS, confidence=0.9):
    return Diagnosis(signal_id="s1", root_cause=root_cause, confidence=confidence, reasoning="test")


def test_opted_out_customer_is_stopped():
    sig = _signal(customer_id="opted_out_customer")
    db.record_opt_out("opted_out_customer")
    d = decide(sig, _diag())
    assert d.stop is True
    assert d.stop_reason == "customer_opted_out"


def test_compliance_sensitive_root_cause_always_escalates_and_stops():
    sig = _signal()
    d = decide(sig, _diag(root_cause=RootCause.INVOICE_DISPUTE))
    assert d.escalate is True
    assert d.stop is True


def test_high_value_signal_escalates_but_does_not_stop():
    # Payment failure threshold is 20000 -- this is well above it.
    sig = _signal(amount=99000)
    d = decide(sig, _diag())
    assert d.escalate is True
    assert d.stop is False


def test_receivable_threshold_is_scoped_higher_than_payment_threshold():
    # A payment failure at this amount escalates; a receivable at the same
    # amount should not, since B2B invoices are naturally higher-value.
    payment_sig = _signal(stype=SignalType.PAYMENT_FAILURE, amount=99000)
    receivable_sig = _signal(stype=SignalType.OVERDUE_RECEIVABLE, amount=99000, customer_id="c2")

    payment_decision = decide(payment_sig, _diag())
    receivable_decision = decide(receivable_sig, _diag(root_cause=RootCause.CASH_FLOW_DELAY))

    assert payment_decision.escalate is True
    assert receivable_decision.escalate is False


def test_max_contact_attempts_stops_further_outreach():
    sig = _signal(customer_id="c_over_limit")
    for _ in range(3):
        db.record_contact("c_over_limit", "s1", "sms")
    d = decide(sig, _diag())
    assert d.stop is True
    assert d.stop_reason == "max_contact_attempts_reached"


def test_quiet_hours_uses_ist_not_utc():
    # 18:30 UTC == midnight IST -- squarely inside default quiet hours
    # (21:00-09:00 IST). If this were checked in UTC instead, 18:30 would
    # be outside the UTC 21-9 window and incorrectly allow contact.
    midnight_ist_in_utc = datetime(2026, 1, 1, 18, 30)
    assert _in_quiet_hours(midnight_ist_in_utc) is True

    # 10:00 UTC == 15:30 IST -- squarely inside business hours, not quiet.
    afternoon_ist_in_utc = datetime(2026, 1, 1, 10, 0)
    assert _in_quiet_hours(afternoon_ist_in_utc) is False
