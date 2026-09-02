from datetime import datetime, timedelta

import pytest

import app.engine.policy as policy
import app.integrations.llm as llm_module
from app import db
from app.config import settings
from app.engine.actions import execute
from app.engine.agent import refine_decision
from app.engine.pipeline import process_batch, release_due_deferrals
from app.engine.policy import decide
from app.models import (
    ActionStatus, AgentRecommendation, Channel, Decision, Diagnosis, RootCause, Signal, SignalType,
)

NOW = datetime(2026, 6, 1, 10, 0)  # daytime IST, well clear of quiet hours


def _signal(amount=2500, lang="en"):
    return Signal(
        type=SignalType.PAYMENT_FAILURE, customer_id="c1", customer_name="Test User",
        amount=amount, language_pref=lang, metadata={"reason_code": "card_expired"},
    )


def _diag():
    return Diagnosis(signal_id="s", root_cause=RootCause.CARD_EXPIRED, confidence=0.97, reasoning="x")


def _proceeding(sig):
    return Decision(
        signal_id=sig.id, playbook="payment_retry", escalate=False, stop=False,
        stop_reason=None, plan=["diagnose:card_expired", "execute:payment_retry"],
    )


def _agent_says(monkeypatch, **kwargs):
    monkeypatch.setattr(settings, "USE_AI_RECOVERY_AGENT", True, raising=False)

    def _fn(signal, diagnosis, context):
        return AgentRecommendation(
            signal_id=signal.id, action=kwargs.get("action", "proceed"),
            confidence=0.9, reasoning=kwargs.get("reasoning", "because"),
            channel=kwargs.get("channel"), defer_hours=kwargs.get("defer_hours", 0),
        )

    monkeypatch.setattr(llm_module, "llm_recommend_action", _fn, raising=False)


# --------------------------------------------------------------------------
# Channel selection
# --------------------------------------------------------------------------

def test_agent_can_choose_a_channel_the_playbook_supports(monkeypatch):
    monkeypatch.setattr(policy, "_in_quiet_hours", lambda *a, **k: False)
    _agent_says(monkeypatch, channel="whatsapp")
    sig = _signal(lang="en")  # default for payment_retry in English would be SMS

    decision = refine_decision(sig, _diag(), _proceeding(sig), now_utc=NOW)
    assert decision.channel_override == "whatsapp"
    assert "ai_channel:whatsapp" in decision.plan

    result = execute(sig, decision, now_utc=NOW)
    assert result.channel == Channel.WHATSAPP, "the agent's channel choice must actually be used"


def test_a_channel_the_playbook_cannot_deliver_is_discarded(monkeypatch):
    # payment_retry has no email path. A model naming one must not cause an
    # unsupported send -- the playbook's own default takes over instead.
    monkeypatch.setattr(policy, "_in_quiet_hours", lambda *a, **k: False)
    _agent_says(monkeypatch, channel="email")
    sig = _signal(lang="en")

    decision = refine_decision(sig, _diag(), _proceeding(sig), now_utc=NOW)
    assert decision.channel_override is None
    assert not any(p.startswith("ai_channel:") for p in decision.plan)

    result = execute(sig, decision, now_utc=NOW)
    assert result.channel == Channel.SMS, "must fall back to the playbook default"


def test_channel_and_delay_are_ignored_for_a_non_proceed_action(monkeypatch):
    _agent_says(monkeypatch, action="escalate", channel="whatsapp", defer_hours=5)
    sig = _signal()

    decision = refine_decision(sig, _diag(), _proceeding(sig), now_utc=NOW)
    assert decision.escalate is True
    assert decision.channel_override is None
    assert decision.defer_hours == 0


# --------------------------------------------------------------------------
# Deferral: the agent may postpone, never accelerate
# --------------------------------------------------------------------------

def test_a_deferred_signal_is_not_contacted_now_and_is_persisted(monkeypatch):
    monkeypatch.setattr(policy, "_in_quiet_hours", lambda *a, **k: False)
    _agent_says(monkeypatch, defer_hours=6)
    sig = _signal()

    decision = refine_decision(sig, _diag(), _proceeding(sig), now_utc=NOW)
    assert decision.defer_hours == 6
    assert "ai_defer:6h" in decision.plan

    result = execute(sig, decision, now_utc=NOW)
    assert result.status == ActionStatus.DEFERRED
    assert result.message_sent is None, "a deferred signal must not contact anyone yet"
    assert result.channel == Channel.NONE

    stored = db.list_due_deferred_signals(NOW + timedelta(hours=7))
    assert len(stored) == 1
    assert stored[0]["signal"]["id"] == sig.id


@pytest.mark.parametrize("requested,expected", [(-5, 0), (0, 0), (3, 3)])
def test_a_negative_delay_is_clamped_so_the_agent_can_never_contact_sooner(
    monkeypatch, requested, expected
):
    monkeypatch.setattr(policy, "_in_quiet_hours", lambda *a, **k: False)
    _agent_says(monkeypatch, defer_hours=requested)
    sig = _signal()
    decision = refine_decision(sig, _diag(), _proceeding(sig), now_utc=NOW)
    assert decision.defer_hours == expected


def test_a_deferral_is_not_released_before_its_time():
    sig = _signal()
    db.record_deferred_signal(
        {**sig.__dict__, "type": sig.type.value},
        not_before=(NOW + timedelta(hours=8)).isoformat(),
        reason="test",
    )
    assert release_due_deferrals(NOW) == []
    assert release_due_deferrals(NOW + timedelta(hours=4)) == []


def test_a_due_deferral_is_released_exactly_once():
    sig = _signal()
    db.record_deferred_signal(
        {**sig.__dict__, "type": sig.type.value},
        not_before=(NOW + timedelta(hours=2)).isoformat(),
        reason="test",
    )
    later = NOW + timedelta(hours=3)

    first = release_due_deferrals(later)
    assert [s.id for s in first] == [sig.id]
    assert release_due_deferrals(later) == [], "a released deferral must not be replayed"


def test_a_released_signal_re_enters_the_batch_and_is_actually_sent(monkeypatch):
    monkeypatch.setattr(policy, "_in_quiet_hours", lambda *a, **k: False)
    monkeypatch.setattr(settings, "USE_AI_RECOVERY_AGENT", False, raising=False)
    sig = _signal()
    db.record_deferred_signal(
        {**sig.__dict__, "type": sig.type.value},
        not_before=(NOW + timedelta(hours=2)).isoformat(),
        reason="test",
    )

    traces = process_batch([], now_utc=NOW + timedelta(hours=3), show_progress=False)

    assert len(traces) == 1, "the due deferral should have joined the batch on its own"
    assert traces[0].signal.id == sig.id
    assert traces[0].action.status in {ActionStatus.SENT, ActionStatus.RECOVERED}


def test_a_signal_deferred_into_quiet_hours_is_stopped_not_sent(monkeypatch):
    # The safety property that makes deferral acceptable at all: a released
    # signal is re-evaluated against EVERY guardrail at the later clock, so
    # the agent cannot use a delay to land outreach somewhere the rules
    # would never have allowed it.
    monkeypatch.setattr(settings, "USE_AI_RECOVERY_AGENT", False, raising=False)
    sig = _signal()
    db.record_deferred_signal(
        {**sig.__dict__, "type": sig.type.value},
        not_before=(NOW + timedelta(hours=2)).isoformat(),
        reason="test",
    )

    # 18:00 UTC == 23:30 IST -- inside quiet hours.
    traces = process_batch(
        [], now_utc=datetime(2026, 6, 1, 18, 0), show_progress=False
    )

    assert len(traces) == 1
    assert traces[0].action.status == ActionStatus.STOPPED
    assert traces[0].action.details["reason"] == "quiet_hours"
