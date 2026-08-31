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


def process_batch(signals: List[Signal], now_utc: Optional[datetime] = None) -> List[Trace]:
    db.init_db()
    return [process_signal(s, now_utc=now_utc) for s in signals]
