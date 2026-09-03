"""Regression test: /api/run-batch used to never log a `batch_detection`
marker (only scripts/run_batch.py did), so dashboard_data.py's _latest_batch
fell back to whatever marker a previous CLI run had left -- or none at all --
and every subsequent API-triggered run silently accumulated into that window
instead of being reported on its own terms. Repeated clicks of "Run batch" in
the frontend, with no --reset in between, is exactly this scenario."""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_two_consecutive_api_run_batches_each_report_their_own_detection_stats():
    first = client.post("/api/run-batch", params={"n": 12, "seed": 1}).json()
    second = client.post("/api/run-batch", params={"n": 30, "seed": 2}).json()

    assert first["detection"]["raw_cases"] == 12
    assert second["detection"]["raw_cases"] == 30
    assert second["totals"]["signals"] == second["detection"]["signals_detected"]


def test_malformed_simulate_time_is_a_clean_400_not_an_unhandled_500():
    response = client.post("/api/run-batch", params={"n": 3, "simulate_time": "not-a-date"})
    assert response.status_code == 400
    assert "not-a-date" in response.json()["detail"]
