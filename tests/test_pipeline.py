from app.data.synthetic_generator import generate_batch
from app.engine.pipeline import process_batch
from app.reporting.batch_report import generate_report


def test_full_batch_runs_without_crashing_and_report_is_consistent():
    signals = generate_batch(n=40, seed=123)
    traces = process_batch(signals)
    assert len(traces) == 40

    report = generate_report(traces)
    assert report["batch_size"] == 40
    assert report["total_recovered_amount"] <= report["total_at_risk_amount"]
    assert 0.0 <= report["recovery_rate"] <= 1.0

    # Every trace must have produced a real action outcome, never an
    # unhandled crash mid-batch.
    statuses = {t.action.status.value for t in traces}
    assert statuses.issubset({"sent", "recovered", "failed", "escalated", "stopped", "skipped"})
