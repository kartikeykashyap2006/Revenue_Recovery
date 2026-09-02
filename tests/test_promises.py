"""Promise-to-pay is one of the brief's named directions, and it used to be
write-only: a promise was recorded with fulfilled=False and then nothing ever
read it -- no follow-up, nothing marking it kept or broken. These pin the
behaviour that makes it an actual tracker."""
from datetime import datetime, timedelta

import app.engine.policy as policy
from app import db
from app.config import settings
from app.engine.pipeline import process_batch, resolve_due_promises
from app.engine.policy import decide
from app.models import ActionStatus, Diagnosis, RootCause, Signal, SignalType

NOW = datetime(2026, 5, 1, 10, 0)


def _receivable(amount=45000.0):
    return Signal(
        type=SignalType.OVERDUE_RECEIVABLE, customer_id="biz_1", customer_name="Test Co",
        amount=amount, metadata={"reason_code": "cash_flow", "due_date": "2026-04-01",
                                 "invoice_id": "inv_1"},
    )


def _promise(sig, days=7):
    db.record_promise_to_pay(
        {**sig.__dict__, "type": sig.type.value},
        promised_date=(NOW + timedelta(days=days)).isoformat(),
    )


def test_a_promise_is_not_judged_before_its_date():
    sig = _receivable()
    _promise(sig, days=7)

    assert resolve_due_promises(NOW) == []
    assert resolve_due_promises(NOW + timedelta(days=3)) == []
    assert db.list_due_promises(NOW + timedelta(days=3)) == []


def test_a_kept_promise_is_marked_kept_and_does_not_come_back():
    # "Kept" is judged against confirmed money from the confirmation stage,
    # not against whether an outreach was sent.
    sig = _receivable()
    _promise(sig)
    db.record_pending_recovery(
        signal_id=sig.id, playbook="receivables_chaser", amount=sig.amount,
        reference="inv_1", recovery_probability=1.0,
    )
    db.confirm_recovery(sig.id, confirmed=True, source="test")

    released = resolve_due_promises(NOW + timedelta(days=8))

    assert released == [], "a customer who paid must not be chased or escalated"
    stages = [e["stage"] for e in db.fetch_audit_log(sig.id)]
    assert "promise_kept" in stages
    stored = db._load_state()["promises_to_pay"][0]
    assert stored["status"] == "kept" and stored["fulfilled"] is True


def test_a_broken_promise_comes_back_flagged():
    sig = _receivable()
    _promise(sig)
    # no confirmed recovery recorded -- the date simply passes

    released = resolve_due_promises(NOW + timedelta(days=8))

    assert len(released) == 1
    assert released[0].metadata["promise_broken"] is True
    stages = [e["stage"] for e in db.fetch_audit_log(sig.id)]
    assert "promise_broken" in stages
    assert db._load_state()["promises_to_pay"][0]["status"] == "broken"


def test_a_broken_promise_escalates_to_a_human_rather_than_being_chased_again():
    # The customer made an explicit commitment and missed it. That buys a
    # human, never another automated contact.
    sig = _receivable()
    sig.metadata["promise_broken"] = True
    diag = Diagnosis(signal_id=sig.id, root_cause=RootCause.CASH_FLOW_DELAY,
                     confidence=0.75, reasoning="x")

    decision = decide(sig, diag, now_utc=NOW)

    assert decision.escalate is True
    assert decision.stop is True
    assert decision.stop_reason == "broken_promise_to_pay"


def test_a_promise_is_judged_exactly_once():
    sig = _receivable()
    _promise(sig)
    later = NOW + timedelta(days=8)

    first = resolve_due_promises(later)
    assert len(first) == 1
    assert resolve_due_promises(later) == [], "a promise must not be re-judged"


def test_end_to_end_a_broken_promise_surfaces_as_an_escalated_case(monkeypatch):
    monkeypatch.setattr(settings, "USE_AI_RECOVERY_AGENT", False, raising=False)
    monkeypatch.setattr(policy, "_in_quiet_hours", lambda *a, **k: False)
    sig = _receivable()
    _promise(sig)

    traces = process_batch([], now_utc=NOW + timedelta(days=8), show_progress=False)

    assert len(traces) == 1, "the broken promise should have joined the batch on its own"
    assert traces[0].action.status == ActionStatus.ESCALATED
    assert traces[0].action.details["reason"] == "broken_promise_to_pay"
