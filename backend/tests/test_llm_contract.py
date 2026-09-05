"""Guards on the prompt<->context contract.

These exist because a mismatch between the prompt template's placeholders
and the keyword arguments passed to .format() raises inside
llm_recommend_action's try/except, which converts it into a safe fallback --
so the whole agent would quietly degrade to "no real answers, 100%
fallback" with nothing in the logs pointing at the actual cause. That
failure is invisible without a test and only reproduces against the real
API, which is the worst possible place to discover it."""
from datetime import datetime

import app.integrations.llm as llm
from app import db
from app.config import settings
from app.engine.agent import build_context
from app.models import Decision, Diagnosis, RootCause, Signal, SignalType

NOW = datetime(2026, 6, 1, 10, 0)


def _context(playbook="payment_retry", customer_id="c1"):
    sig = Signal(
        type=SignalType.PAYMENT_FAILURE, customer_id=customer_id, customer_name="Test",
        amount=2500, metadata={"reason_code": "card_expired"},
    )
    diag = Diagnosis(signal_id=sig.id, root_cause=RootCause.CARD_EXPIRED, confidence=0.97, reasoning="x")
    decision = Decision(
        signal_id=sig.id, playbook=playbook, escalate=False, stop=False, stop_reason=None,
    )
    return sig, diag, build_context(sig, diag, decision, NOW)


def _enable(monkeypatch, captured):
    monkeypatch.setattr(settings, "USE_AI_RECOVERY_AGENT", True, raising=False)
    monkeypatch.setattr(settings, "LLM_PROVIDER", "nvidia", raising=False)
    monkeypatch.setattr(settings, "NVIDIA_API_KEY", "test-key", raising=False)

    def _fake_call(prompt, max_tokens=200):
        captured.append(prompt)
        return '{"action": "proceed", "channel": null, "defer_hours": 0, ' \
               '"confidence": 0.9, "reasoning": "ok"}'

    monkeypatch.setattr(llm, "_call_llm", _fake_call)


def test_the_agent_prompt_renders_without_a_missing_placeholder(monkeypatch):
    captured = []
    _enable(monkeypatch, captured)
    sig, diag, ctx = _context()

    result = llm.llm_recommend_action(sig, diag, ctx)

    assert result is not None
    assert result.error is None, (
        f"prompt/context contract broke, which would show up only as a 100% "
        f"fallback rate against the real API: {result.error}"
    )
    assert result.action == "proceed"
    assert captured, "the prompt was never built"


def test_the_prompt_actually_carries_the_channel_evidence(monkeypatch):
    # The channel choice is only meaningful if the model can see what has
    # already been tried -- without this it returns the same blanket answer
    # for every customer.
    db.record_contact("c_repeat", "sig_old", "sms")
    db.record_contact("c_repeat", "sig_old2", "sms")

    captured = []
    _enable(monkeypatch, captured)
    sig, diag, ctx = _context(customer_id="c_repeat")

    llm.llm_recommend_action(sig, diag, ctx)

    prompt = captured[0]
    assert "Channels already tried" in prompt
    assert "sms" in prompt, "prior channel attempts must reach the model"


def test_channel_history_counts_attempts_and_which_ones_recovered():
    db.record_contact("c9", "sig_a", "sms")
    db.record_contact("c9", "sig_b", "sms")
    db.record_contact("c9", "sig_c", "whatsapp")
    db.record_pending_recovery(
        signal_id="sig_c", playbook="payment_retry", amount=100.0,
        reference="plink_x", recovery_probability=1.0,
    )
    db.confirm_recovery("sig_c", confirmed=True, source="test")

    history = db.get_channel_history("c9")

    assert history["sms"] == {"attempts": 2, "recovered": 0}
    assert history["whatsapp"] == {"attempts": 1, "recovered": 1}


def test_channel_history_is_empty_for_a_customer_never_contacted():
    # The common case in a fresh batch -- and the case where the agent is
    # told it has no grounds to override the playbook's default.
    assert db.get_channel_history("never_seen") == {}
