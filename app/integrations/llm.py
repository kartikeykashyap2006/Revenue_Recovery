"""Optional LLM-assisted diagnosis and recovery-decision functions.

Both entry points here are only invoked when their respective feature
flags AND the configured provider's credentials are set, so the pipeline
still runs fully deterministically offline for fast iteration/demo
without needing any LLM access at all -- and both degrade to a safe,
logged default on any failure (bad key, network error, malformed
response) rather than raising.

Two providers are supported, selected by settings.LLM_PROVIDER:
- "anthropic" (default): the Claude API. Needs ANTHROPIC_API_KEY and
  billing set up on the account.
- "gemini": Google's hosted Gemini API, calling a Gemma model. Needs
  GEMINI_API_KEY (free via https://aistudio.google.com/apikey, no
  billing required to start).

Both go through _call_llm() below, so llm_diagnose and
llm_recommend_action don't know or care which one answered -- same
prompts, same bounded JSON schemas, same fallback behavior either way.
"""
import json
import random
import time
from typing import Optional

from app.config import settings
from app.models import AgentRecommendation, Signal, RootCause, Diagnosis

_ROOT_CAUSE_VALUES = [c.value for c in RootCause]


def _llm_configured() -> bool:
    if settings.LLM_PROVIDER == "gemini":
        return bool(settings.GEMINI_API_KEY)
    return bool(settings.ANTHROPIC_API_KEY)


def _extract_json(text: str) -> dict:
    """Smaller/open models are more prone than Claude to wrapping JSON in
    a markdown code fence despite being told not to -- strip one off if
    present, then parse. Raises (like a bare json.loads would) on
    anything that still isn't valid JSON, which callers already catch."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    return json.loads(text)


# Whether this Gemma/Gemini model honors generationConfig.thinkingConfig
# (see _gemini_generate). None = not yet discovered, True/False once a real
# call has told us. Cached process-wide so the discovery cost is paid at
# most once per run, not once per signal.
_GEMINI_MINIMAL_THINKING_SUPPORTED = None

# Transient upstream failures worth one retry rather than an immediate
# fallback to the deterministic default: rate limiting (very reachable on a
# free tier once calls run concurrently) and upstream unavailability.
_RETRYABLE_HTTP_CODES = {429, 500, 502, 503, 504}
_MAX_TRANSIENT_RETRIES = 2


def _gemini_payload(prompt: str, max_tokens: int, minimal_thinking: bool) -> bytes:
    """Builds one generateContent request body.

    `minimal_thinking` asks Gemma to skip its internal reasoning pass. That
    pass is the single biggest cost in this system: for a bounded
    three-way classification, a trivial prompt was measured generating 169
    thinking tokens to produce a 21-token answer -- ~89% of everything
    generated, and generation is sequential, so it dominates wall-clock
    time (~5.4s/call). Suppressing it is worth several-fold speedup, but
    the controls are unreliable on Gemma specifically (thinkingBudget is
    rejected outright; includeThoughts is silently ignored), so this is
    attempted optimistically and abandoned permanently the moment the API
    rejects it -- see _gemini_generate.

    maxOutputTokens stays padded regardless: if thinking is NOT suppressed,
    a tight budget gets consumed mid-thought and returns no usable answer
    at all (finishReason=MAX_TOKENS with only a "thought" part).
    """
    generation_config = {"maxOutputTokens": max(max_tokens, 2048), "temperature": 0.2}
    if minimal_thinking:
        generation_config["thinkingConfig"] = {"thinkingLevel": "MINIMAL"}
    return json.dumps(
        {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": generation_config,
        }
    ).encode()


def _gemini_post(payload: bytes, timeout: int = 30) -> dict:
    import urllib.request

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{settings.GEMINI_MODEL}:generateContent?key={settings.GEMINI_API_KEY}"
    )
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _gemini_post_with_retry(payload: bytes) -> dict:
    """One retry pass over transient upstream failures. Concurrency (see
    app/engine/pipeline.py's prefetch) makes free-tier rate limiting a
    realistic occurrence rather than a theoretical one, and a 429 that
    silently degrades to the deterministic default is a worse outcome than
    waiting a second and asking again."""
    import urllib.error

    for attempt in range(_MAX_TRANSIENT_RETRIES + 1):
        try:
            return _gemini_post(payload)
        except urllib.error.HTTPError as exc:
            retryable = exc.code in _RETRYABLE_HTTP_CODES
            if not retryable or attempt == _MAX_TRANSIENT_RETRIES:
                raise
            time.sleep(1.5 * (2 ** attempt) + random.uniform(0, 0.4))


def _gemini_generate(prompt: str, max_tokens: int) -> str:
    """Calls Gemma via the hosted Gemini API, preferring the no-thinking
    fast path and permanently falling back if this model rejects it."""
    import urllib.error

    global _GEMINI_MINIMAL_THINKING_SUPPORTED
    try_minimal = _GEMINI_MINIMAL_THINKING_SUPPORTED is not False

    try:
        data = _gemini_post_with_retry(_gemini_payload(prompt, max_tokens, try_minimal))
        if try_minimal:
            _GEMINI_MINIMAL_THINKING_SUPPORTED = True
    except urllib.error.HTTPError as exc:
        # A 400 on the optimistic attempt means this model doesn't accept
        # thinkingConfig -- remember that and never pay for the rejection
        # again, then immediately retry the same prompt without it so the
        # caller never sees a failure it didn't need to see.
        if try_minimal and exc.code == 400:
            _GEMINI_MINIMAL_THINKING_SUPPORTED = False
            data = _gemini_post_with_retry(_gemini_payload(prompt, max_tokens, False))
        else:
            raise

    # Skip any part marked "thought": true -- when thinking isn't
    # suppressed, the model's internal scratchpad comes back as its own
    # part alongside the real answer, and joining them would feed the
    # scratchpad into the JSON parser.
    parts = data["candidates"][0]["content"]["parts"]
    answer = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    if not answer:
        candidate = data["candidates"][0]
        raise ValueError(
            f"Gemini/Gemma response had no non-thought text (finishReason="
            f"{candidate.get('finishReason')!r}, thoughtsTokenCount="
            f"{data.get('usageMetadata', {}).get('thoughtsTokenCount')!r}); "
            f"try a higher max_tokens"
        )
    return answer


def _call_llm(prompt: str, max_tokens: int = 200) -> str:
    """Sends `prompt` to whichever provider is configured and returns the
    raw response text. Raises on any failure -- every caller wraps this
    in a try/except and falls back to a safe deterministic default,
    exactly the same way regardless of provider."""
    if settings.LLM_PROVIDER == "gemini":
        return _gemini_generate(prompt, max_tokens)

    import anthropic

    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    resp = client.messages.create(
        model="claude-3-5-haiku-latest",
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text


_PROMPT_TEMPLATE = """You are a revenue-recovery diagnosis assistant for a payments company.
Given a signal about at-risk revenue, pick the single best root cause from this list:
{causes}

Signal type: {signal_type}
Amount: {amount} {currency}
Metadata: {metadata}

Respond with strict JSON, and nothing else, no markdown formatting: {{"root_cause": "<one of the list>", "confidence": <0-1 float>, "reasoning": "<one sentence>"}}
"""


def llm_diagnose(signal: Signal) -> Optional[Diagnosis]:
    if not settings.USE_LLM_DIAGNOSIS or not _llm_configured():
        return None
    try:
        prompt = _PROMPT_TEMPLATE.format(
            causes=", ".join(_ROOT_CAUSE_VALUES),
            signal_type=signal.type.value,
            amount=signal.amount,
            currency=signal.currency,
            metadata=json.dumps(signal.metadata, default=str),
        )
        data = _extract_json(_call_llm(prompt, max_tokens=200))
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


_AGENT_ALLOWED_ACTIONS = {"proceed", "hold", "escalate"}

_AGENT_PROMPT_TEMPLATE = """You are a bounded recovery-decision agent for a payments company's revenue-recovery system.

This specific signal has ALREADY cleared every deterministic compliance/safety guardrail (opt-outs, mandatory-escalation root causes, high-value thresholds, max-contact-attempts, cooldown, quiet hours) and is cleared to proceed with its assigned recovery playbook. Your only job is to sanity-check that call using the context below -- most of the time "proceed" is correct, but you may override it for this specific case if something in the context genuinely warrants more caution than the deterministic rules alone applied.

Signal type: {signal_type}
Amount: {amount} {currency}
Diagnosed root cause: {root_cause} (rule confidence: {diagnosis_confidence})
Assigned playbook: {playbook}
Customer's prior contact attempts on record: {prior_contact_attempts}
Customer language preference: {language_pref}
Additional context: {extra_context}

Choose exactly one action:
- "proceed": go ahead with the assigned playbook as planned.
- "hold": don't contact the customer this round (e.g. already close to the contact limit, or outreach right now seems premature for this specific case) -- explain why.
- "escalate": flag this specific case for human review even though it didn't trip an automatic escalation rule (e.g. borderline-high amount, unusually low diagnosis confidence, or something in the context looks atypical for this root cause).

Respond with strict JSON, and nothing else, no markdown formatting: {{"action": "<one of proceed|hold|escalate>", "confidence": <0-1 float>, "reasoning": "<one or two sentences, specific to this case>"}}
"""


def llm_recommend_action(signal: Signal, diagnosis: Diagnosis, context: dict) -> Optional[AgentRecommendation]:
    """Asks the configured LLM to sanity-check (never expand) the
    deterministic policy engine's decision to proceed with a signal's
    assigned playbook. `context` is built by app.engine.agent._build_context
    from real state (contact history, metadata) -- nothing here is
    invented.

    Returns None only when the feature is off or unconfigured (no call
    attempted at all, matching llm_diagnose's convention). Once a call IS
    attempted, this always returns an AgentRecommendation -- on any
    failure (bad key, network error, unparseable/out-of-set response) it
    returns one with action="proceed" and `error` set, so a flaky call
    degrades to the deterministic default rather than ever crashing the
    batch or silently doing nothing."""
    if not settings.USE_AI_RECOVERY_AGENT or not _llm_configured():
        return None
    try:
        core_keys = {
            "signal_type", "amount", "currency", "root_cause",
            "diagnosis_confidence", "playbook", "prior_contact_attempts", "language_pref",
        }
        extra = {k: v for k, v in context.items() if k not in core_keys}
        prompt = _AGENT_PROMPT_TEMPLATE.format(
            signal_type=context["signal_type"],
            amount=context["amount"],
            currency=context["currency"],
            root_cause=context["root_cause"],
            diagnosis_confidence=context["diagnosis_confidence"],
            playbook=context["playbook"],
            prior_contact_attempts=context["prior_contact_attempts"],
            language_pref=context["language_pref"],
            extra_context=json.dumps(extra, default=str),
        )
        data = _extract_json(_call_llm(prompt, max_tokens=200))
        action = data.get("action")
        if action not in _AGENT_ALLOWED_ACTIONS:
            return AgentRecommendation(
                signal_id=signal.id, action="proceed", confidence=0.0,
                reasoning=data.get("reasoning", ""),
                error=f"model returned an action outside the bounded set: {action!r}",
            )
        return AgentRecommendation(
            signal_id=signal.id,
            action=action,
            confidence=float(data.get("confidence", 0.0)),
            reasoning=data.get("reasoning", ""),
        )
    except Exception as exc:  # best-effort fallback, never crash the pipeline
        return AgentRecommendation(
            signal_id=signal.id, action="proceed", confidence=0.0,
            reasoning="agent call failed; defaulting to the deterministic decision",
            error=str(exc),
        )
