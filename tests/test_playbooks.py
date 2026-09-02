import random

import app.engine.policy as policy
from app.engine.actions import execute
from app.engine.policy import decide
from app.models import Signal, SignalType, RootCause, Diagnosis, Decision, ActionStatus
from app.playbooks import receivables_chaser
from app import db


def test_payment_retry_playbook_always_sends_a_link_and_message(monkeypatch):
    # Isolate this test from the real wall-clock quiet-hours check -- it's
    # testing the playbook mechanics, not the quiet-hours policy (which has
    # its own dedicated, time-controlled test in test_policy.py).
    monkeypatch.setattr(policy, "_in_quiet_hours", lambda *a, **k: False)
    sig = Signal(
        type=SignalType.PAYMENT_FAILURE, customer_id="c1", customer_name="Aarav Sharma",
        amount=2500, metadata={"reason_code": "card_expired"},
    )
    decision = decide(sig, Diagnosis(signal_id=sig.id, root_cause=RootCause.CARD_EXPIRED, confidence=0.97, reasoning="x"))
    result = execute(sig, decision)
    # A playbook only ever sends -- it never decides "recovered" for
    # itself. See app/engine/confirmation.py for where RECOVERED actually
    # gets decided, as a separate, distinctly-audited step.
    assert result.status == ActionStatus.SENT
    assert result.amount_recovered == 0.0
    assert result.message_sent is not None
    assert "rzp.io/mock" in result.details["payment_link"]

    pending = db.list_unconfirmed_recoveries()
    assert any(r["signal_id"] == sig.id and r["amount"] == 2500 for r in pending)


def test_hinglish_message_used_when_language_pref_is_hi(monkeypatch):
    monkeypatch.setattr(policy, "_in_quiet_hours", lambda *a, **k: False)
    sig = Signal(
        type=SignalType.PAYMENT_FAILURE, customer_id="c1", customer_name="Priya Verma",
        amount=1500, language_pref="hi", metadata={"reason_code": "insufficient_funds"},
    )
    decision = decide(sig, Diagnosis(signal_id=sig.id, root_cause=RootCause.INSUFFICIENT_FUNDS, confidence=0.9, reasoning="x"))
    result = execute(sig, decision)
    assert "Namaste" in result.message_sent


def test_receivables_chaser_can_record_a_promise_to_pay():
    sig = Signal(
        type=SignalType.OVERDUE_RECEIVABLE, customer_id="biz_1", customer_name="Test Co",
        amount=45000, metadata={"reason_code": "cash_flow", "due_date": "2026-08-01"},
    )
    decision = Decision(signal_id=sig.id, playbook="receivables_chaser", escalate=False, stop=False, stop_reason=None)

    # Sweep several seeds deterministically until we hit the promise-to-pay
    # branch, proving the mechanism actually works end-to-end (not just
    # that the code parses).
    found_promise = False
    for seed in range(50):
        random.seed(seed)
        result = receivables_chaser.run(sig, decision)
        if result.details.get("promise_to_pay_recorded"):
            found_promise = True
            break
    assert found_promise, "promise-to-pay branch never fired across 50 seeds"

    promises = db._load_state()["promises_to_pay"]
    assert len(promises) >= 1
    assert promises[0]["customer_id"] == "biz_1"


def test_playbook_exception_is_caught_and_becomes_failed_result_not_a_crash(monkeypatch):
    from app.playbooks import payment_retry

    def boom(*args, **kwargs):
        raise RuntimeError("simulated Razorpay outage")

    monkeypatch.setattr(payment_retry, "run", boom)
    # actions.PLAYBOOKS captured the original function reference at import
    # time, so patch the registry entry directly for this test.
    from app.engine import actions
    monkeypatch.setitem(actions.PLAYBOOKS, "payment_retry", boom)

    sig = Signal(type=SignalType.PAYMENT_FAILURE, customer_id="c1", customer_name="X", amount=100)
    decision = Decision(signal_id=sig.id, playbook="payment_retry", escalate=False, stop=False, stop_reason=None)
    result = execute(sig, decision)
    assert result.status == ActionStatus.FAILED
    assert "simulated Razorpay outage" in result.details["error"]


def test_one_signals_full_audit_trace_includes_the_outreach_message(monkeypatch):
    # Regression test for a broken demo path: app/integrations/messaging.py
    # used to file message_sent events under the CUSTOMER id while every
    # other stage of the same signal was filed under the SIGNAL id, so
    # `inspect_audit.py --signal-id <id>` -- the walk-one-trace-end-to-end
    # beat in docs/pitch_outline.md -- showed diagnosis/decision/action/
    # confirmation but silently dropped the actual message that was sent.
    monkeypatch.setattr(policy, "_in_quiet_hours", lambda *a, **k: False)
    sig = Signal(
        type=SignalType.PAYMENT_FAILURE, customer_id="c_trace", customer_name="Trace Test",
        amount=1500, metadata={"reason_code": "card_expired"},
    )
    decision = decide(sig, Diagnosis(signal_id=sig.id, root_cause=RootCause.CARD_EXPIRED, confidence=0.97, reasoning="x"))
    execute(sig, decision)

    stages = [e["stage"] for e in db.fetch_audit_log(sig.id)]
    assert any(s.startswith("message_sent:") for s in stages), (
        f"a signal's own trace must include the outreach message sent for it; got {stages}"
    )
