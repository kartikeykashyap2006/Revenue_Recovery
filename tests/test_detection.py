from datetime import datetime, timedelta

from app.data.raw_events import RawEvent
from app.engine.detection import detect_signals
from app.models import SignalType


def _event(event_type, case_id, ts, **payload):
    return RawEvent(
        event_type=event_type, case_id=case_id, customer_id="cust_1",
        customer_name="Test User", amount=1000.0, currency="INR",
        timestamp=ts, payload=payload,
    )


def test_a_case_that_resolved_on_its_own_produces_no_signal():
    now = datetime(2026, 1, 1, 12, 0)
    events = [
        _event("payment.failed", "case_1", now - timedelta(hours=2), error_code="card_expired"),
        _event("payment.captured", "case_1", now - timedelta(hours=1)),
    ]
    assert detect_signals(events, now_utc=now) == []


def test_an_unresolved_payment_failure_produces_a_signal_with_the_right_reason_code():
    now = datetime(2026, 1, 1, 12, 0)
    events = [
        _event("payment.failed", "case_2", now - timedelta(hours=2),
               error_code="card_expired", payment_method="card", phone="9123456780", email="a@x.com"),
    ]
    signals = detect_signals(events, now_utc=now)
    assert len(signals) == 1
    assert signals[0].type == SignalType.PAYMENT_FAILURE
    assert signals[0].metadata["reason_code"] == "card_expired"
    assert signals[0].metadata["phone"] == "9123456780"


def test_subscription_attempt_count_reflects_actual_failed_events_not_a_random_draw():
    now = datetime(2026, 1, 1, 12, 0)
    events = [
        _event("subscription.charge.failed", "case_3", now - timedelta(days=3), error_code="insufficient_funds", attempt=1),
        _event("subscription.charge.failed", "case_3", now - timedelta(days=2), error_code="insufficient_funds", attempt=2),
        _event("subscription.charge.failed", "case_3", now - timedelta(days=1), error_code="card_expired", attempt=3),
    ]
    signals = detect_signals(events, now_utc=now)
    assert len(signals) == 1
    assert signals[0].type == SignalType.SUBSCRIPTION_MANDATE_FAILURE
    assert signals[0].metadata["attempt_count"] == 3
    assert signals[0].metadata["reason_code"] == "card_expired"  # the latest attempt's code


def test_a_resolved_subscription_case_produces_no_signal():
    now = datetime(2026, 1, 1, 12, 0)
    events = [
        _event("subscription.charge.failed", "case_4", now - timedelta(days=2), error_code="mandate_expired", attempt=1),
        _event("subscription.charge.succeeded", "case_4", now - timedelta(days=1)),
    ]
    assert detect_signals(events, now_utc=now) == []


def test_an_invoice_not_yet_due_produces_no_signal_even_if_unpaid():
    now = datetime(2026, 1, 1, 12, 0)
    future_due = (now + timedelta(days=5)).date().isoformat()
    events = [
        _event("invoice.created", "case_5", now - timedelta(days=10),
               invoice_id="inv_5", due_date=future_due, status_hint="no_response"),
    ]
    assert detect_signals(events, now_utc=now) == []


def test_an_overdue_unpaid_invoice_produces_an_overdue_receivable_signal():
    now = datetime(2026, 1, 1, 12, 0)
    past_due = (now - timedelta(days=10)).date().isoformat()
    events = [
        _event("invoice.created", "case_6", now - timedelta(days=40),
               invoice_id="inv_6", due_date=past_due, status_hint="disputed"),
    ]
    signals = detect_signals(events, now_utc=now)
    assert len(signals) == 1
    assert signals[0].type == SignalType.OVERDUE_RECEIVABLE
    assert signals[0].metadata["reason_code"] == "disputed"
    assert signals[0].metadata["invoice_id"] == "inv_6"


def test_a_paid_invoice_produces_no_signal_regardless_of_due_date():
    now = datetime(2026, 1, 1, 12, 0)
    past_due_dt = now - timedelta(days=10)
    events = [
        _event("invoice.created", "case_7", now - timedelta(days=40),
               invoice_id="inv_7", due_date=past_due_dt.date().isoformat(), status_hint="cash_flow"),
        _event("invoice.paid", "case_7", past_due_dt + timedelta(days=1)),
    ]
    assert detect_signals(events, now_utc=now) == []


def test_mixed_stream_of_multiple_cases_only_signals_the_unresolved_ones():
    now = datetime(2026, 1, 1, 12, 0)
    events = [
        _event("payment.failed", "resolved_case", now - timedelta(hours=3), error_code="otp_mismatch"),
        _event("payment.captured", "resolved_case", now - timedelta(hours=2)),
        _event("payment.failed", "unresolved_case", now - timedelta(hours=1), error_code="gateway_timeout"),
        _event("checkout.session.started", "abandoned_case", now - timedelta(hours=5), friction_hint="price_page_exit"),
    ]
    signals = detect_signals(events, now_utc=now)
    types = [s.type for s in signals]
    assert len(signals) == 2  # only the two unresolved cases
    assert SignalType.PAYMENT_FAILURE in types
    assert SignalType.CHECKOUT_ABANDONMENT in types
