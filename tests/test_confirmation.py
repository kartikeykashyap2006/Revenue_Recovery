import app.engine.confirmation as confirmation_module
from app import db
from app.engine.confirmation import (
    confirm_from_live_link_status,
    confirm_from_webhook,
    reconcile_pending_recoveries,
    simulate_pending_confirmations,
)
from app.models import (
    ActionResult, ActionStatus, Channel, Diagnosis, Decision, RootCause, Signal, SignalType, Trace,
)


def _trace_with_pending_recovery(amount=1000.0, reference="plink_test123", probability=1.0):
    sig = Signal(type=SignalType.PAYMENT_FAILURE, customer_id="c1", customer_name="Test", amount=amount)
    diagnosis = Diagnosis(signal_id=sig.id, root_cause=RootCause.CARD_EXPIRED, confidence=0.9, reasoning="x")
    decision = Decision(signal_id=sig.id, playbook="payment_retry", escalate=False, stop=False, stop_reason=None)
    action = ActionResult(
        signal_id=sig.id, playbook="payment_retry", channel=Channel.SMS, status=ActionStatus.SENT,
        message_sent="hi", amount_recovered=0.0, details={"recovery_confirmation": "pending"},
    )
    db.record_pending_recovery(
        signal_id=sig.id, playbook="payment_retry", amount=amount,
        reference=reference, recovery_probability=probability,
    )
    return Trace(signal=sig, diagnosis=diagnosis, decision=decision, action=action)


def test_simulate_confirmation_marks_recovered_when_probability_is_certain():
    trace = _trace_with_pending_recovery(amount=5000.0, probability=1.0)
    recovered_count = simulate_pending_confirmations([trace])

    assert recovered_count == 1
    assert trace.action.status == ActionStatus.RECOVERED
    assert trace.action.amount_recovered == 5000.0
    assert trace.action.details["confirmed_via"] == "simulated_gateway_confirmation"

    entries = db.fetch_audit_log(trace.signal.id)
    confirmation_events = [e for e in entries if e["stage"] == "confirmation"]
    assert len(confirmation_events) == 1
    assert confirmation_events[0]["payload"]["confirmed"] is True
    assert confirmation_events[0]["payload"]["source"] == "simulated_gateway_confirmation"


def test_simulate_confirmation_leaves_sent_when_probability_is_zero():
    trace = _trace_with_pending_recovery(amount=3000.0, probability=0.0)
    recovered_count = simulate_pending_confirmations([trace])

    assert recovered_count == 0
    assert trace.action.status == ActionStatus.SENT
    assert trace.action.amount_recovered == 0.0
    assert trace.action.details["recovery_confirmation"] == "unconfirmed"


def test_simulate_confirmation_only_resolves_each_pending_recovery_once():
    trace = _trace_with_pending_recovery(amount=1000.0, probability=1.0)
    simulate_pending_confirmations([trace])
    # A second pass over the same traces must be a no-op: the pending
    # recovery was already resolved, so list_unconfirmed_recoveries() no
    # longer includes it.
    recovered_count_second_pass = simulate_pending_confirmations([trace])
    assert recovered_count_second_pass == 0
    assert len(db.fetch_audit_log(trace.signal.id)) == 1  # still exactly one confirmation event


def test_webhook_confirmation_finds_and_resolves_matching_pending_recovery():
    trace = _trace_with_pending_recovery(amount=7500.0, reference="plink_realtest", probability=1.0)

    record = confirm_from_webhook("plink_realtest", paid=True)

    assert record is not None
    assert record["signal_id"] == trace.signal.id
    entries = db.fetch_audit_log(trace.signal.id)
    confirmation_events = [e for e in entries if e["stage"] == "confirmation"]
    assert confirmation_events[0]["payload"]["source"] == "razorpay_webhook"
    assert confirmation_events[0]["payload"]["confirmed"] is True

    # Note: unlike simulate_pending_confirmations, confirm_from_webhook
    # resolves state.json directly and does not know about any in-memory
    # Trace object -- the caller (app.main's webhook handler) has no
    # batch of traces to mutate, since the webhook can arrive long after
    # the batch that sent the link has already finished and been reported.


def test_webhook_confirmation_returns_none_for_unknown_reference():
    assert confirm_from_webhook("plink_never_created", paid=True) is None


def _fake_razorpay(status, live=True):
    class _Stub:
        @staticmethod
        def fetch_payment_link_status(link_id):
            return {"status": status, "live": live}
    return _Stub


def test_live_link_poll_confirms_a_paid_link(monkeypatch):
    trace = _trace_with_pending_recovery(amount=2500.0, reference="plink_LIVE123", probability=0.0)
    monkeypatch.setattr(confirmation_module, "razorpay_client", _fake_razorpay("paid"))

    record = confirm_from_live_link_status("plink_LIVE123")

    assert record is not None
    assert record["confirmed"] is True
    assert record["confirmed_via"] == "razorpay_link_poll"
    events = db.fetch_audit_log(trace.signal.id)
    confirmations = [e for e in events if e["stage"] == "confirmation"]
    assert confirmations and confirmations[0]["payload"]["source"] == "razorpay_link_poll"
    assert confirmations[0]["payload"]["amount"] == 2500.0


def test_live_link_poll_records_an_unpaid_link_as_not_recovered(monkeypatch):
    _trace_with_pending_recovery(amount=800.0, reference="plink_LIVE_EXPIRED", probability=1.0)
    monkeypatch.setattr(confirmation_module, "razorpay_client", _fake_razorpay("expired"))

    record = confirm_from_live_link_status("plink_LIVE_EXPIRED")

    assert record is not None
    assert record["confirmed"] is False


def test_live_link_poll_is_a_no_op_for_mock_links(monkeypatch):
    _trace_with_pending_recovery(reference="plink_mock_abc123")
    # A mock link has no upstream status -- the client reports live=False.
    monkeypatch.setattr(confirmation_module, "razorpay_client", _fake_razorpay("unknown", live=False))

    assert confirm_from_live_link_status("plink_mock_abc123") is None
    assert db.list_unconfirmed_recoveries(), "a mock link must stay unconfirmed, not be silently resolved"


def test_reconcile_skips_mock_references_entirely(monkeypatch):
    _trace_with_pending_recovery(reference="plink_mock_skipme")
    _trace_with_pending_recovery(reference="plink_LIVE_real", amount=1200.0)
    monkeypatch.setattr(confirmation_module, "razorpay_client", _fake_razorpay("paid"))

    result = reconcile_pending_recoveries()

    assert result["checked"] == 1, "mock links must not be polled"
    assert result["resolved"] == 1
    assert result["recovered"] == 1
