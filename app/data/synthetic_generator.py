"""Generates batches of at-risk-revenue Signal objects for offline
demoing and testing without needing live Razorpay traffic.

This is now a thin wrapper: it generates a raw, unlabeled event stream
(app.data.raw_events) and runs it through the actual detection layer
(app.engine.detection) rather than handing out pre-labeled signals
directly. `n` is the number of underlying raw event-cases simulated, not
a guaranteed output count -- some fraction of cases resolve on their own
(a retried payment goes through, a customer comes back and pays, an
invoice gets settled) and correctly produce no signal at all, since a
real detection system wouldn't raise an alert for a problem that already
resolved itself. See app/engine/detection.py for why this split exists.
"""
from datetime import datetime
from typing import List, Optional

from app.data.raw_events import generate_raw_event_stream
from app.engine.detection import detect_signals
from app.models import Signal


def generate_batch(
    n: int = 60, seed: Optional[int] = None, now_utc: Optional[datetime] = None
) -> List[Signal]:
    now_utc = now_utc or datetime.utcnow()
    events = generate_raw_event_stream(n_cases=n, seed=seed, now_utc=now_utc)
    return detect_signals(events, now_utc=now_utc)
