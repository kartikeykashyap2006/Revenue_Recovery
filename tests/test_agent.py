from datetime import datetime

from app import db
from app.config import settings
from app.engine.agent import build_context, context_fingerprint, refine_decision
from app.models import AgentRecommendation, Decision, Diagnosis, RootCause, Signal, SignalType
import app.integrations.llm as llm_module


def _signal():
    return Signal(type=SignalType.PAYMENT_FAILURE, customer_id="c1", customer_name="Test", amount=1000)


def _diag():
    return Diagnosis(signal_id="s1", root_cause=RootCause.CARD_EXPIRED, confidence=0.9, reasoning="x")


def _proceeding_decision(sig):
    return Decision(
        signal_id=sig.id, playbook="payment_retry", escalate=False, stop=False,
        stop_reason=None, plan=["diagnose:card_expired", "execute:payment_retry"],
    )


def test_agent_is_a_no_op_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "USE_AI_RECOVERY_AGENT", False, raising=False)
    sig = _signal()
    decision = _proceeding_decision(sig)
    result = refine_decision(sig, _diag(), decision)
    assert result is decision
    assert db.fetch_audit_log(sig.id) == []


def test_agent_is_never_consulted_for_an_already_stopped_or_escalated_decision(monkeypatch):
    monkeypatch.setattr(settings, "USE_AI_RECOVERY_AGENT", True, raising=False)
    called = []
    monkeypatch.setattr(llm_module, "llm_recommend_action", lambda *a, **k: called.append(1), raising=False)

    sig = _signal()
    stopped = Decision(signal_id=sig.id, playbook="payment_retry", escalate=False, stop=True,
                        stop_reason="cooldown_active", plan=[])
    result = refine_decision(sig, _diag(), stopped)
    assert result is stopped
    assert called == [], "agent must never be consulted once policy already stopped/escalated a decision"


def test_agent_proceed_recommendation_keeps_decision_but_annotates_plan(monkeypatch):
    monkeypatch.setattr(settings, "USE_AI_RECOVERY_AGENT", True, raising=False)
    sig = _signal()
    monkeypatch.setattr(
        llm_module, "llm_recommend_action",
        lambda *a, **k: AgentRecommendation(signal_id=sig.id, action="proceed", confidence=0.8, reasoning="fine"),
        raising=False,
    )
    decision = _proceeding_decision(sig)
    result = refine_decision(sig, _diag(), decision)

    assert result.escalate is False
    assert result.stop is False
    assert "ai_agent:proceed" in result.plan

    events = db.fetch_audit_log(sig.id)
    assert any(e["stage"] == "ai_recommendation" for e in events)


def test_agent_hold_recommendation_stops_the_decision(monkeypatch):
    monkeypatch.setattr(settings, "USE_AI_RECOVERY_AGENT", True, raising=False)
    sig = _signal()
    monkeypatch.setattr(
        llm_module, "llm_recommend_action",
        lambda *a, **k: AgentRecommendation(signal_id=sig.id, action="hold", confidence=0.7, reasoning="risky timing"),
        raising=False,
    )
    result = refine_decision(sig, _diag(), _proceeding_decision(sig))

    assert result.stop is True
    assert result.stop_reason == "ai_recommended_hold"
    assert result.escalate is False


def test_agent_escalate_recommendation_escalates_without_stopping(monkeypatch):
    monkeypatch.setattr(settings, "USE_AI_RECOVERY_AGENT", True, raising=False)
    sig = _signal()
    monkeypatch.setattr(
        llm_module, "llm_recommend_action",
        lambda *a, **k: AgentRecommendation(signal_id=sig.id, action="escalate", confidence=0.6, reasoning="looks off"),
        raising=False,
    )
    result = refine_decision(sig, _diag(), _proceeding_decision(sig))

    assert result.escalate is True
    assert result.stop is False
    assert result.stop_reason == "ai_flagged_for_review"


def test_agent_none_recommendation_is_a_safe_no_op(monkeypatch):
    # llm_recommend_action itself returns None when unconfigured (missing
    # key) even if USE_AI_RECOVERY_AGENT is True at the config level.
    monkeypatch.setattr(settings, "USE_AI_RECOVERY_AGENT", True, raising=False)
    sig = _signal()
    monkeypatch.setattr(llm_module, "llm_recommend_action", lambda *a, **k: None, raising=False)
    decision = _proceeding_decision(sig)
    result = refine_decision(sig, _diag(), decision)

    assert result is decision
    assert db.fetch_audit_log(sig.id) == []


def test_agent_context_uses_simulated_now_not_real_wall_clock(monkeypatch):
    # Regression test: the agent must reason using the batch's simulated
    # now_utc (see --simulate-time in scripts/run_batch.py), not its own
    # training-time guess at "today" -- otherwise it can (and did, before
    # this fix) claim a genuinely overdue invoice's due_date is "in the
    # future, a data error" purely because it had no grounded reference
    # point for what day it's supposed to be evaluating against.
    monkeypatch.setattr(settings, "USE_AI_RECOVERY_AGENT", True, raising=False)
    sig = _signal()
    captured = {}

    def _capture(signal, diagnosis, context):
        captured.update(context)
        return AgentRecommendation(signal_id=sig.id, action="proceed", confidence=0.9, reasoning="ok")

    monkeypatch.setattr(llm_module, "llm_recommend_action", _capture, raising=False)

    simulated_now = datetime(2026, 1, 1, 10, 0)
    refine_decision(sig, _diag(), _proceeding_decision(sig), now_utc=simulated_now)

    assert captured["current_date"] == "2026-01-01"


def _counting_llm(calls, action="proceed", reasoning="inline call"):
    def _fn(signal, diagnosis, context):
        calls.append(context)
        return AgentRecommendation(
            signal_id=signal.id, action=action, confidence=0.5, reasoning=reasoning
        )
    return _fn


def test_a_matching_prefetched_recommendation_is_used_without_another_model_call(monkeypatch):
    # The whole point of the parallel prefetch (app/engine/pipeline.py) is that
    # the sequential loop reuses the answer instead of paying for the call
    # twice -- if this regresses, batches silently double their model calls.
    monkeypatch.setattr(settings, "USE_AI_RECOVERY_AGENT", True, raising=False)
    sig = _signal()
    calls = []
    monkeypatch.setattr(llm_module, "llm_recommend_action", _counting_llm(calls), raising=False)

    now = datetime(2026, 1, 1, 10, 0)
    decision = _proceeding_decision(sig)
    context = build_context(sig, _diag(), decision, now)
    prefetched = AgentRecommendation(
        signal_id=sig.id, action="escalate", confidence=0.9, reasoning="from prefetch"
    )
    cache = {sig.id: (context_fingerprint(context), prefetched)}

    result = refine_decision(sig, _diag(), decision, now_utc=now, cache=cache)

    assert calls == [], "a valid cached recommendation must not trigger a second model call"
    assert result.escalate is True, "the cached recommendation must actually be applied"
    assert result.stop_reason == "ai_flagged_for_review"


def test_a_stale_prefetched_recommendation_is_discarded_and_refetched(monkeypatch):
    # A prefetched answer is speculative: it's fetched before the batch mutates
    # contact history. If the situation changed, reusing that advice would mean
    # acting on a model opinion about a DIFFERENT set of facts, so it must be
    # thrown away rather than trusted.
    monkeypatch.setattr(settings, "USE_AI_RECOVERY_AGENT", True, raising=False)
    sig = _signal()
    calls = []
    monkeypatch.setattr(llm_module, "llm_recommend_action", _counting_llm(calls), raising=False)

    decision = _proceeding_decision(sig)
    # Fingerprint built against a different reference date than the one the
    # real decision is made with -- stands in for any context drift.
    stale_context = build_context(sig, _diag(), decision, datetime(2020, 1, 1, 10, 0))
    stale = AgentRecommendation(
        signal_id=sig.id, action="escalate", confidence=0.9, reasoning="stale advice"
    )
    cache = {sig.id: (context_fingerprint(stale_context), stale)}

    result = refine_decision(
        sig, _diag(), decision, now_utc=datetime(2026, 1, 1, 10, 0), cache=cache
    )

    assert len(calls) == 1, "a stale cache entry must fall through to a fresh call"
    assert result.escalate is False, "the stale 'escalate' must not have been applied"
    assert "ai_agent:proceed" in result.plan


def test_prefetch_is_a_no_op_when_the_agent_is_disabled(monkeypatch):
    from app.data.raw_events import generate_raw_event_stream
    from app.engine.detection import detect_signals
    from app.engine.pipeline import prefetch_agent_recommendations

    monkeypatch.setattr(settings, "USE_AI_RECOVERY_AGENT", False, raising=False)
    calls = []
    monkeypatch.setattr(llm_module, "llm_recommend_action", _counting_llm(calls), raising=False)

    now = datetime(2026, 1, 1, 10, 0)
    signals = detect_signals(generate_raw_event_stream(10, seed=1, now_utc=now), now_utc=now)

    assert prefetch_agent_recommendations(signals, now_utc=now) == {}
    assert calls == [], "no model call may be made while the agent is switched off"


def test_a_full_batch_consults_the_model_at_most_once_per_signal(monkeypatch):
    # End-to-end guard against the prefetch and the sequential loop each
    # making their own call for the same signal.
    from app.data.raw_events import generate_raw_event_stream
    from app.engine.detection import detect_signals
    from app.engine.pipeline import process_batch

    monkeypatch.setattr(settings, "USE_AI_RECOVERY_AGENT", True, raising=False)
    calls = []
    monkeypatch.setattr(llm_module, "llm_recommend_action", _counting_llm(calls), raising=False)

    now = datetime(2026, 1, 1, 10, 0)
    signals = detect_signals(generate_raw_event_stream(25, seed=11, now_utc=now), now_utc=now)
    traces = process_batch(signals, now_utc=now, show_progress=False)

    consulted = [t for t in traces if any(p.startswith("ai_agent:") for p in t.decision.plan)]
    assert consulted, "this batch should have reached the agent for at least one signal"
    assert len(calls) <= len(signals), (
        f"made {len(calls)} model calls for {len(signals)} signals -- the prefetched "
        f"answers are not being reused"
    )
