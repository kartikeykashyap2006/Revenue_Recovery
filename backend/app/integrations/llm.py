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
- "nvidia": NVIDIA's hosted NIM API, calling a Nemotron model. Needs
  NVIDIA_API_KEY (free via https://build.nvidia.com, no billing required
  to start, ~40 RPM on the free tier). The model is a reasoning variant;
  its internal thinking pass is explicitly disabled per request (see
  _nvidia_payload) because reasoning tokens otherwise dominate wall-clock
  time for a bounded few-way classification -- a ~7x per-call speedup
  measured against this model.

Both go through _call_llm() below, so llm_diagnose and
llm_recommend_action don't know or care which one answered -- same
prompts, same bounded JSON schemas, same fallback behavior either way.
"""
import json
import random
import threading
import time
from typing import Optional

from app.config import settings
from app.models import AgentRecommendation, Signal, RootCause, Diagnosis

_ROOT_CAUSE_VALUES = [c.value for c in RootCause]


def _llm_configured() -> bool:
    if settings.LLM_PROVIDER == "nvidia":
        return bool(settings.NVIDIA_API_KEY)
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


# Transient upstream failures worth one retry rather than an immediate
# fallback to the deterministic default: rate limiting (very reachable on a
# free tier once calls run concurrently) and upstream unavailability.
_RETRYABLE_HTTP_CODES = {429, 500, 502, 503, 504}
_MAX_TRANSIENT_RETRIES = 4

# Codes that mean "you are asking for more than there is capacity for right
# now" -- these widen the request interval, not just trigger a retry.
#
# 503 belongs here, and leaving it out was costing whole minutes per batch.
# NVIDIA NIM does NOT signal saturation with 429; it returns
#   503 {"error":{"message":"ResourceExhausted: Worker local total request
#        limit reached (16/16)", ...}}
# because the inference worker is shared across free-tier users. Measured on
# a real batch: 13 of 37 calls came back 503 while only 3 of 116 were ever
# 429. With only 429 wired to back-off, the client stayed blind to the actual
# congestion signal -- it just retried straight back into the full worker,
# and because retries re-enter the throttle, each wasted attempt burned
# another full interval slot plus a backoff sleep. Effective throughput is
# target_rpm * success_rate, so a 65% success rate turned a 40 RPM target
# into ~26 RPM. Backing off on 503 lets the client ride out a busy worker
# instead of hammering it.
_BACKPRESSURE_HTTP_CODES = {429, 503}

# --- Adaptive client-side rate limiting -------------------------------------
#
# Requests are spaced by a shared minimum interval so concurrent workers don't
# hammer the shared NIM worker. The strategy is DISCOVER-AND-BACK-OFF, not
# pace-at-a-fixed-rate: start near the fastest cadence the config allows
# (interval floor = 60 / settings.NVIDIA_MAX_RPM), let sustained success creep
# toward that floor, and widen the interval whenever the worker pushes back
# with a 429 or a 503 "worker full" (see _BACKPRESSURE_HTTP_CODES). Then
# recover fast once it clears.
#
# This beats pacing to a hard "safe" rate because the real constraint isn't a
# clean per-minute cap -- it's shared-worker saturation that comes and goes.
# A measured run in an uncongested window sustained ~44 RPM with zero errors
# by pushing at this low floor; capping the pace at a conservative 40 RPM
# instead just left that headroom on the table without avoiding the 503s that
# a congested window throws regardless. The backpressure widen is what keeps a
# busy worker from being hammered, so being aggressive on the floor is safe.
_nvidia_rate_lock = threading.Lock()
# Fastest cadence the throttle will use (seconds between starts = 60 / RPM).
_NVIDIA_INTERVAL_FLOOR = 60.0 / max(settings.NVIDIA_MAX_RPM, 1)
# Start a touch slower than the floor and let success discover the floor,
# rather than opening with a burst into a worker whose state we don't know.
_NVIDIA_INITIAL_INTERVAL = _NVIDIA_INTERVAL_FLOOR * 1.2
_nvidia_min_request_interval = _NVIDIA_INITIAL_INTERVAL
_NVIDIA_INTERVAL_CEILING = 6.0   # 10 RPM -- a real ceiling on back-off under a genuinely bad window
_NVIDIA_INTERVAL_WIDEN_FACTOR = 1.35    # on 429/503, back off (see note about concurrent bursts below)
_NVIDIA_INTERVAL_NARROW_FACTOR = 0.85   # once it clears, recover fast toward the floor
_nvidia_last_request_at = 0.0


def _nvidia_throttle() -> None:
    global _nvidia_last_request_at
    with _nvidia_rate_lock:
        wait = _nvidia_min_request_interval - (time.monotonic() - _nvidia_last_request_at)
        if wait > 0:
            time.sleep(wait)
        _nvidia_last_request_at = time.monotonic()


def _nvidia_widen_interval() -> None:
    global _nvidia_min_request_interval
    with _nvidia_rate_lock:
        _nvidia_min_request_interval = min(
            _nvidia_min_request_interval * _NVIDIA_INTERVAL_WIDEN_FACTOR, _NVIDIA_INTERVAL_CEILING
        )


def _nvidia_narrow_interval() -> None:
    global _nvidia_min_request_interval
    with _nvidia_rate_lock:
        _nvidia_min_request_interval = max(
            _nvidia_min_request_interval * _NVIDIA_INTERVAL_NARROW_FACTOR, _NVIDIA_INTERVAL_FLOOR
        )


def current_nvidia_request_interval() -> float:
    """The interval the NVIDIA client has settled on for this run (tests/diagnostics)."""
    with _nvidia_rate_lock:
        return _nvidia_min_request_interval


# --- Throttle observability (diagnostics only) ------------------------------
#
# A batch's wall-clock time on the NVIDIA free tier is dominated by shared-
# worker congestion (see the 503 note above) rather than anything in the
# deterministic pipeline, so the useful thing to surface after a run is how
# much backpressure it actually hit and where the interval ended up. These
# counters make that observable instead of guessable -- read them with
# nvidia_throttle_stats(), pair with current_nvidia_request_interval().
_nvidia_stats_lock = threading.Lock()
_nvidia_stats = {"successes": 0, "failures": 0, "http_429": 0, "http_503": 0, "retries": 0}


def _record_nvidia_stat(key: str) -> None:
    with _nvidia_stats_lock:
        _nvidia_stats[key] += 1


def nvidia_throttle_stats() -> dict:
    """Snapshot of NVIDIA request outcomes since the last reset (diagnostics)."""
    with _nvidia_stats_lock:
        return dict(_nvidia_stats)


def reset_nvidia_throttle_stats() -> None:
    with _nvidia_stats_lock:
        for k in _nvidia_stats:
            _nvidia_stats[k] = 0


def _retry_delay(exc, attempt: int) -> float:
    """Prefers the server's own Retry-After over a guess -- it knows when the
    window reopens and we don't."""
    headers = getattr(exc, "headers", None)
    if headers is not None:
        try:
            return min(float(headers.get("Retry-After")), _NVIDIA_INTERVAL_CEILING * 2)
        except (TypeError, ValueError):
            pass
    return min(1.5 * (2 ** attempt), _NVIDIA_INTERVAL_CEILING * 2) + random.uniform(0, 0.5)


def _nvidia_payload(prompt: str, max_tokens: int) -> bytes:
    """Builds one OpenAI-compatible chat-completions request body for
    NVIDIA's hosted NIM API.

    enable_thinking is always sent False: this is a reasoning-variant
    model, and letting it think is pure tax here -- most of the generated
    tokens would be internal scratchpad, not the bounded three-way answer
    this call actually needs, and generation is sequential so that
    scratchpad dominates wall-clock time (a ~7x per-call speedup was
    measured with it off: ~0.9s vs ~6.4s). NVIDIA's docs confirm
    chat_template_kwargs.enable_thinking is honored, so it's simply always
    off -- no discovery or fallback dance needed.
    """
    # chat_template_kwargs belongs at the top level of the request body --
    # "extra_body" is an OpenAI Python SDK convenience name for "merge these
    # keys into the top-level payload", not a real field the raw HTTP API
    # understands; sending it literally gets a 400 ("Unsupported
    # parameter(s): extra_body"), which is how this got caught.
    return json.dumps(
        {
            "model": settings.NVIDIA_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max(max_tokens, 512),
            "temperature": 0.2,
            "chat_template_kwargs": {"enable_thinking": False},
        }
    ).encode()


def _nvidia_post(payload: bytes, timeout: int = 30) -> dict:
    import urllib.request

    req = urllib.request.Request(
        "https://integrate.api.nvidia.com/v1/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.NVIDIA_API_KEY}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _nvidia_post_with_retry(payload: bytes) -> dict:
    """One retry pass over transient upstream failures, spacing request
    starts by the adaptive interval (_nvidia_min_request_interval). A 429
    that silently degrades to the deterministic default is a worse outcome
    than waiting a moment and asking again -- see the comment above
    _nvidia_rate_lock for how the interval self-tunes."""
    import urllib.error

    for attempt in range(_MAX_TRANSIENT_RETRIES + 1):
        _nvidia_throttle()
        try:
            response = _nvidia_post(payload)
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                _record_nvidia_stat("http_429")
            elif exc.code == 503:
                _record_nvidia_stat("http_503")
            if exc.code in _BACKPRESSURE_HTTP_CODES:
                # Slow every worker down, not just this one: capacity is
                # shared per-key (and, for 503, shared across tenants), so
                # one thread seeing it means all of them are pushing too hard.
                _nvidia_widen_interval()
            if exc.code not in _RETRYABLE_HTTP_CODES or attempt == _MAX_TRANSIENT_RETRIES:
                _record_nvidia_stat("failures")
                raise
            _record_nvidia_stat("retries")
            time.sleep(_retry_delay(exc, attempt))
        else:
            _nvidia_narrow_interval()
            _record_nvidia_stat("successes")
            return response


def _nvidia_generate(prompt: str, max_tokens: int) -> str:
    """Calls the configured Nemotron model via NVIDIA's hosted NIM API."""
    data = _nvidia_post_with_retry(_nvidia_payload(prompt, max_tokens))
    choice = data["choices"][0]
    content = choice["message"].get("content") or ""
    if not content:
        raise ValueError(
            f"NVIDIA NIM response had no content (finish_reason="
            f"{choice.get('finish_reason')!r}); try a higher max_tokens"
        )
    return content


def _call_llm(prompt: str, max_tokens: int = 200) -> str:
    """Sends `prompt` to whichever provider is configured and returns the
    raw response text. Raises on any failure -- every caller wraps this
    in a try/except and falls back to a safe deterministic default,
    exactly the same way regardless of provider."""
    if settings.LLM_PROVIDER == "nvidia":
        return _nvidia_generate(prompt, max_tokens)

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

# Upper bound on how long the agent may postpone outreach. A deferral is
# advisory and one-directional: it can push contact later (the agent judging
# now to be a bad moment), never earlier, and never past the point where the
# signal would go stale. Anything outside this range is clamped, not obeyed.
_MAX_DEFER_HOURS = 24

_AGENT_PROMPT_TEMPLATE = """You are a bounded recovery-decision agent for a payments company's revenue-recovery system.

This specific signal has ALREADY cleared every deterministic compliance/safety guardrail (opt-outs, mandatory-escalation root causes, high-value thresholds, max-contact-attempts, cooldown, quiet hours) and is cleared to proceed with its assigned recovery playbook. Your only job is to sanity-check that call using the context below -- most of the time "proceed" is correct, but you may override it for this specific case if something in the context genuinely warrants more caution than the deterministic rules alone applied.

Signal type: {signal_type}
Amount: {amount} {currency}
Diagnosed root cause: {root_cause} (rule confidence: {diagnosis_confidence})
Assigned playbook: {playbook}
Customer's prior contact attempts on record: {prior_contact_attempts}
Customer language preference: {language_pref}
Channels already tried for this customer (attempts, and how many led to a recovery): {channels_already_tried}
Additional context: {extra_context}

Choose exactly one action:
- "proceed": go ahead with the assigned playbook.
- "hold": don't contact the customer this round (e.g. already close to the contact limit, or outreach right now seems premature for this specific case) -- explain why.
- "escalate": flag this specific case for human review even though it didn't trip an automatic escalation rule (e.g. borderline-high amount, unusually low diagnosis confidence, or something in the context looks atypical for this root cause).

If (and only if) you choose "proceed", you may also shape HOW the outreach happens:
- "channel": which channel to use, from this list and no other: {available_channels}. Default to null. The playbook's own default already adapts to the customer's language preference, so only name a channel when "Channels already tried" above gives you a concrete reason to switch -- for example a channel attempted more than once for this customer with no recovery. If that history is empty you have no evidence to justify overriding the default: return null.
- "defer_hours": an integer from 0 to {max_defer_hours}. Use 0 to send now. Use a positive number when contacting immediately looks counterproductive for this specific case and waiting is likely to do better (e.g. a bank-side failure that needs time to clear before a retry has any chance). You can only delay outreach, never bring it forward.

Respond with strict JSON, and nothing else, no markdown formatting: {{"action": "<one of proceed|hold|escalate>", "channel": "<one of {available_channels}, or null>", "defer_hours": <integer 0-{max_defer_hours}>, "confidence": <0-1 float>, "reasoning": "<one or two sentences, specific to this case, mentioning the channel/delay choice if you made one>"}}
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
            "available_channels", "channels_already_tried",
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
            available_channels=", ".join(context.get("available_channels", [])) or "none",
            channels_already_tried=json.dumps(context.get("channels_already_tried", {}), default=str),
            max_defer_hours=_MAX_DEFER_HOURS,
        )
        data = _extract_json(_call_llm(prompt, max_tokens=200))
        action = data.get("action")
        if action not in _AGENT_ALLOWED_ACTIONS:
            return AgentRecommendation(
                signal_id=signal.id, action="proceed", confidence=0.0,
                reasoning=data.get("reasoning", ""),
                error=f"model returned an action outside the bounded set: {action!r}",
            )
        # Validate/clamp before anything reaches a Decision. A model answer
        # is a suggestion about HOW to act, never permission to act
        # differently: an unsupported channel falls back to the playbook's
        # own default, and a defer outside the allowed window is clamped
        # rather than honoured (a negative value could otherwise be read as
        # "contact sooner", which the agent is never allowed to ask for).
        allowed_channels = set(context.get("available_channels", []))
        channel = data.get("channel")
        if channel not in allowed_channels:
            channel = None

        try:
            defer_hours = int(data.get("defer_hours") or 0)
        except (TypeError, ValueError):
            defer_hours = 0
        defer_hours = max(0, min(defer_hours, _MAX_DEFER_HOURS))

        # Channel and delay only mean anything for an outreach that is
        # actually going to happen.
        if action != "proceed":
            channel, defer_hours = None, 0

        return AgentRecommendation(
            signal_id=signal.id,
            action=action,
            confidence=float(data.get("confidence", 0.0)),
            reasoning=data.get("reasoning", ""),
            channel=channel,
            defer_hours=defer_hours,
        )
    except Exception as exc:  # best-effort fallback, never crash the pipeline
        return AgentRecommendation(
            signal_id=signal.id, action="proceed", confidence=0.0,
            reasoning="agent call failed; defaulting to the deterministic decision",
            error=str(exc),
        )
