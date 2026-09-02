from datetime import datetime
from typing import List, Optional

from app import db
from app.models import Signal, SignalType, Trace
from app.engine.diagnosis import diagnose
from app.engine.policy import decide
from app.engine.agent import refine_decision
from app.engine.actions import execute
from app.engine.confirmation import simulate_pending_confirmations
from app.config import settings


def process_signal(
    signal: Signal, now_utc: Optional[datetime] = None, agent_cache: Optional[dict] = None
) -> Trace:
    diagnosis = diagnose(signal)

    if diagnosis.confidence < 0.5 and settings.USE_LLM_DIAGNOSIS:
        from app.integrations.llm import llm_diagnose
        llm_result = llm_diagnose(signal)
        if llm_result is not None:
            diagnosis = llm_result

    db.log_event(signal.id, "diagnosis", diagnosis.__dict__)

    decision = decide(signal, diagnosis, now_utc=now_utc)
    db.log_event(signal.id, "decision", decision.__dict__)

    # Optional AI layer: can only add caution to a decision the
    # deterministic guardrails above already cleared -- see
    # app/engine/agent.py for why it can never loosen one. Logs its own
    # "ai_recommendation" stage; if it actually changed the decision,
    # that's recorded as a distinct "decision_ai_refined" stage so the
    # audit trail shows the deterministic call and the AI-refined call
    # separately, never conflated into one.
    refined = refine_decision(signal, diagnosis, decision, now_utc=now_utc, cache=agent_cache)
    if (refined.stop, refined.escalate, refined.stop_reason) != (decision.stop, decision.escalate, decision.stop_reason):
        db.log_event(signal.id, "decision_ai_refined", refined.__dict__)
    decision = refined

    action = execute(signal, decision, now_utc=now_utc)
    db.log_event(signal.id, "action", action.__dict__)

    if action.channel.value != "none":
        db.record_contact(
            signal.customer_id, signal.id, action.channel.value,
            occurred_at=(now_utc or datetime.utcnow()).isoformat(),
        )

    return Trace(signal=signal, diagnosis=diagnosis, decision=decision, action=action)


def release_due_deferrals(now_utc=None) -> List[Signal]:
    """Rebuilds any signals whose AI-requested wait has now elapsed, so they
    re-enter the batch.

    This is the half that makes a deferral real rather than a note in a log.
    A released signal is NOT fast-tracked: it goes through diagnosis, every
    compliance guardrail, and the agent again, evaluated against the later
    clock -- so a signal deferred into quiet hours is simply stopped when it
    comes back, exactly as a fresh signal would be.
    """
    released: List[Signal] = []
    for record in db.list_due_deferred_signals(now_utc):
        raw = dict(record["signal"])
        try:
            raw["type"] = SignalType(raw["type"])
            signal = Signal(**raw)
        except (ValueError, TypeError):
            continue  # unreadable record -- skip rather than crash the batch
        if db.release_deferred_signal(signal.id):
            released.append(signal)
    return released


def prefetch_agent_recommendations(
    signals: List[Signal], now_utc: Optional[datetime] = None, show_progress: bool = False
) -> dict:
    """Issues the AI agent's consultations concurrently, ahead of the main
    loop, and returns a {signal_id: (context_fingerprint, recommendation)}
    cache for process_signal to draw from.

    Why this exists: model calls are the entire cost of a batch. The whole
    deterministic pipeline processes 30 signals in ~0.25s; a single agent
    consultation takes ~5.4s, and issued one-at-a-time that turns a 30-signal
    batch into minutes of waiting.

    Why it prefetches rather than parallelising the pipeline itself: the
    guardrails are order-dependent (cooldown and max-contact-attempts read
    contact history that earlier signals in the same batch write), and the
    JSON state store does unlocked read-modify-write. Running the pipeline
    concurrently would both corrupt that state and silently weaken
    compliance checks -- an unacceptable trade for speed. So the pipeline
    stays strictly sequential and only the network waits move off the
    critical path.

    The prefetch is therefore speculative: it decides who to ask using a
    provisional decision computed before the batch has mutated any state.
    Anything that turns out stale is caught by the fingerprint check in
    agent.refine_decision and simply re-fetched inline, so correctness never
    depends on the guess being right -- only speed does. Signals that end up
    stopped by a guardrail just leave their prefetched answer unused.
    """
    if not settings.USE_AI_RECOVERY_AGENT:
        return {}

    from concurrent.futures import ThreadPoolExecutor, as_completed

    from app.engine.agent import build_context, context_fingerprint
    from app.integrations.llm import llm_recommend_action

    reference_now = now_utc or datetime.utcnow()
    jobs = []
    for signal in signals:
        provisional_diagnosis = diagnose(signal)
        provisional_decision = decide(signal, provisional_diagnosis, now_utc=now_utc)
        if provisional_decision.stop or provisional_decision.escalate:
            continue  # a guardrail already settles this one; the agent is never consulted
        context = build_context(signal, provisional_diagnosis, provisional_decision, reference_now)
        jobs.append((signal, provisional_diagnosis, context))

    if not jobs:
        return {}

    workers = max(1, min(settings.AI_AGENT_MAX_CONCURRENCY, len(jobs)))
    if show_progress:
        print(
            f"  Consulting the AI recovery-decision agent for {len(jobs)} signal(s) "
            f"({workers} in parallel)...",
            flush=True,
        )

    cache: dict = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(llm_recommend_action, signal, diagnosis, context): (signal, context)
            for signal, diagnosis, context in jobs
        }
        for future in as_completed(futures):
            signal, context = futures[future]
            try:
                recommendation = future.result()
            except Exception:
                # A prefetch failure is never fatal: the signal simply gets a
                # normal inline call later, which has its own safe fallback.
                continue
            if recommendation is not None:
                cache[signal.id] = (context_fingerprint(context), recommendation)
    return cache


def process_batch(
    signals: List[Signal], now_utc: Optional[datetime] = None, show_progress: bool = True
) -> List[Trace]:
    db.init_db()

    # Signals the agent asked to postpone in an earlier run, whose wait has
    # now elapsed, join this batch and are re-evaluated from scratch.
    due = release_due_deferrals(now_utc)
    if due:
        if show_progress:
            print(
                f"  Releasing {len(due)} previously deferred signal(s) whose wait has elapsed.",
                flush=True,
            )
        signals = list(due) + list(signals)

    # Network waits happen here, concurrently, before the sequential loop --
    # see prefetch_agent_recommendations for why the loop itself stays serial.
    agent_cache = prefetch_agent_recommendations(signals, now_utc=now_utc, show_progress=show_progress)

    traces = []
    total = len(signals)
    for i, s in enumerate(signals, start=1):
        trace = process_signal(s, now_utc=now_utc, agent_cache=agent_cache)
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

    # Every playbook only ever sends an outreach (status SENT) -- it never
    # decides "recovered" for itself. This is the confirmation pass that
    # turns pending sends into confirmed RECOVERED outcomes (or leaves
    # them unconfirmed), simulating the external world (did the customer
    # actually pay) as its own distinct, audited step rather than baking
    # that decision into the agent's own reasoning. See
    # app/engine/confirmation.py for why this exists and how a real
    # Razorpay webhook plugs into the same mechanism.
    simulate_pending_confirmations(traces, now_utc=now_utc, show_progress=show_progress)
    return traces
