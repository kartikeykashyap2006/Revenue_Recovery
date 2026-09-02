from datetime import datetime

from app import db
from app.data.synthetic_generator import generate_batch
from app.engine.pipeline import process_batch
from app.models import ActionStatus
from app.reporting.batch_report import generate_report


def test_full_batch_runs_without_crashing_and_report_is_consistent():
    # generate_batch's n is the number of raw event-cases simulated, not a
    # guaranteed signal count -- detection correctly drops any case that
    # resolved on its own (see app/engine/detection.py), so the batch that
    # actually reaches the pipeline is some fraction of n, never more.
    signals = generate_batch(n=40, seed=123)
    assert 0 < len(signals) <= 40
    traces = process_batch(signals, show_progress=False)
    assert len(traces) == len(signals)

    report = generate_report(traces)
    assert report["batch_size"] == len(traces)
    assert report["total_recovered_amount"] <= report["total_at_risk_amount"]
    assert 0.0 <= report["recovery_rate"] <= 1.0

    # Every trace must have produced a real action outcome, never an
    # unhandled crash mid-batch.
    statuses = {t.action.status.value for t in traces}
    assert statuses.issubset({"sent", "recovered", "failed", "escalated", "stopped", "skipped"})


def test_recovered_outcomes_are_always_backed_by_a_confirmation_audit_event():
    # Regression test for the "how do you know this was actually
    # recovered?" gap: a RECOVERED trace must never come from a playbook
    # deciding its own outcome -- it must always be traceable to a
    # distinct "confirmation" audit event (see app/engine/confirmation.py).
    # Fixed daytime-IST now_utc, same pattern as test_policy.py's quiet-hours
    # test -- otherwise this is flaky depending on the real wall-clock time
    # the suite happens to run at (quiet hours would stop every signal
    # before any playbook, and pending confirmed recoveries, ever exist).
    signals = generate_batch(n=40, seed=123)
    traces = process_batch(signals, now_utc=datetime(2026, 1, 1, 10, 0), show_progress=False)

    recovered_traces = [t for t in traces if t.action.status == ActionStatus.RECOVERED]
    assert recovered_traces, "seed 123/n=40 should produce at least one recovery"

    for t in recovered_traces:
        entries = db.fetch_audit_log(t.signal.id)
        confirmations = [e for e in entries if e["stage"] == "confirmation" and e["payload"]["confirmed"]]
        assert confirmations, f"signal {t.signal.id} is RECOVERED but has no confirmation audit event"
        assert t.action.amount_recovered == confirmations[0]["payload"]["amount"]
