from datetime import datetime
from typing import List, Optional

from app import db
from app.models import Signal, Trace
from app.engine.diagnosis import diagnose
from app.engine.policy import decide
from app.engine.actions import execute
from app.config import settings


def process_signal(signal: Signal, now_utc: Optional[datetime] = None) -> Trace:
    diagnosis = diagnose(signal)

    if diagnosis.confidence < 0.5 and settings.USE_LLM_DIAGNOSIS:
        from app.integrations.llm import llm_diagnose
        llm_result = llm_diagnose(signal)
        if llm_result is not None:
            diagnosis = llm_result

    db.log_event(signal.id, "diagnosis", diagnosis.__dict__)

    decision = decide(signal, diagnosis, now_utc=now_utc)
    db.log_event(signal.id, "decision", decision.__dict__)

    action = execute(signal, decision)
    db.log_event(signal.id, "action", action.__dict__)

    if action.channel.value != "none":
        db.record_contact(signal.customer_id, signal.id, action.channel.value)

    return Trace(signal=signal, diagnosis=diagnosis, decision=decision, action=action)


def process_batch(
    signals: List[Signal], now_utc: Optional[datetime] = None, show_progress: bool = True
) -> List[Trace]:
    db.init_db()
    traces = []
    total = len(signals)
    for i, s in enumerate(signals, start=1):
        trace = process_signal(s, now_utc=now_utc)
        traces.append(trace)
        if show_progress:
            # Real Razorpay API calls are rate-limited to ~1/sec (see
            # app/integrations/razorpay_client.py), so a full batch can take
            # over a minute with no other output -- print progress so this
            # doesn't look hung, especially live on camera for a demo.
            print(
                f"  [{i}/{total}] {trace.signal.type.value:30s} "
                f"{trace.signal.customer_name:20s} -> {trace.action.status.value}",
                flush=True,
            )
    return traces
