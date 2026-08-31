"""Optional LLM-assisted diagnosis for low-confidence / unmatched signals.

Only invoked when USE_LLM_DIAGNOSIS=true and ANTHROPIC_API_KEY is set, so
the pipeline still runs fully deterministically offline for fast
iteration/demo without needing an API key."""
import json
from typing import Optional

from app.config import settings
from app.models import Signal, RootCause, Diagnosis

_ROOT_CAUSE_VALUES = [c.value for c in RootCause]

_PROMPT_TEMPLATE = """You are a revenue-recovery diagnosis assistant for a payments company.
Given a signal about at-risk revenue, pick the single best root cause from this list:
{causes}

Signal type: {signal_type}
Amount: {amount} {currency}
Metadata: {metadata}

Respond with strict JSON: {{"root_cause": "<one of the list>", "confidence": <0-1 float>, "reasoning": "<one sentence>"}}
"""


def llm_diagnose(signal: Signal) -> Optional[Diagnosis]:
    if not settings.USE_LLM_DIAGNOSIS or not settings.ANTHROPIC_API_KEY:
        return None
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        prompt = _PROMPT_TEMPLATE.format(
            causes=", ".join(_ROOT_CAUSE_VALUES),
            signal_type=signal.type.value,
            amount=signal.amount,
            currency=signal.currency,
            metadata=json.dumps(signal.metadata, default=str),
        )
        resp = client.messages.create(
            model="claude-3-5-haiku-latest",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()
        data = json.loads(text)
        return Diagnosis(
            signal_id=signal.id,
            root_cause=RootCause(data["root_cause"]),
            confidence=float(data["confidence"]),
            reasoning=data["reasoning"],
        )
    except Exception as exc:  # best-effort fallback, never crash the pipeline
        return Diagnosis(
            signal_id=signal.id,
            root_cause=RootCause.UNKNOWN,
            confidence=0.0,
            reasoning=f"LLM diagnosis failed: {exc}",
        )
