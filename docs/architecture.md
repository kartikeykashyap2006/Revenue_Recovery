# Architecture — AI Revenue Recovery Agent

> Code paths in this document (`app/…`, `scripts/…`, `tests/…`) are relative
> to the `backend/` folder. The TypeScript UI lives in `frontend/` and renders
> the payload built by `app/reporting/dashboard_data.py`, which is the same
> function the offline HTML dashboard uses.

## Problem

Revenue leaks out of a payments business through several different doors at
once: a card payment degrades and fails, a customer abandons checkout, a
subscription's auto-debit mandate stops working, or a B2B invoice goes
unpaid past its due date. Each of these looks like a different problem on
the surface, but they share the same underlying shape: something that was
supposed to convert into revenue didn't, there's usually a diagnosable
reason why, and there is a bounded, safe intervention that can win some of
it back.

## Design: one engine, pluggable playbooks

Rather than building four separate bots, the system is one reusable
pipeline applied to four signal types:

```
raw events -> detect (is this at risk? which category?)
           -> diagnose (root cause) -> decide (playbook + guardrails)
           -> [optional AI agent: proceed / hold / escalate] -> act (playbook)
           -> confirm (recovered or not) -> log (audit trail, every stage)
```

- **`app/models.py`** — the shared vocabulary: `Signal`, `Diagnosis`,
  `Decision`, `ActionResult`, `AgentRecommendation`, `Trace`.
- **`app/data/raw_events.py` + `app/engine/detection.py`** — see "Signal
  detection" below: turns an unlabeled raw event stream into `Signal`
  objects, instead of handing out pre-categorized fixtures.
- **`app/engine/diagnosis.py`** — rule-based root-cause classification per
  signal type (e.g. `insufficient_funds`, `mandate_expired`,
  `invoice_dispute`). Falls back to an LLM (`app/integrations/llm.py`,
  Claude) for low-confidence/unmatched cases when `USE_LLM_DIAGNOSIS=true` —
  the system runs fully deterministically without an LLM key too.
- **`app/engine/policy.py`** — chooses the playbook and applies every
  compliance guardrail *before* any customer contact happens: opt-outs,
  root causes that must go to a human (e.g. suspected fraud/risk decline,
  disputed invoices), high-value escalation, max-contact-attempts, a
  cooldown between attempts, and quiet hours (no outreach 9pm–9am).
- **`app/engine/agent.py`** — optional AI recovery-decision layer (see
  "AI recovery-decision agent" below) that can add caution to -- but never
  loosen -- a decision `policy.py` already cleared for execution.
- **`app/engine/actions.py` + `app/playbooks/*.py`** — one module per
  scenario (`payment_retry`, `checkout_dropoff`, `subscription_mandate`,
  `receivables_chaser`), each producing a customer-facing recovery action
  (payment link + message) and registering a pending recovery for the
  confirmation step below -- no playbook decides "recovered" for itself.
- **`app/db.py`** — file-backed audit trail (append-only `audit_log.jsonl`).
  Every diagnosis, decision, and action is logged with its reasoning, plus
  contact history (for the stopping rules) and a promise-to-pay tracker for
  the B2B receivables flow, stored in `state.json`.
- **`app/reporting/batch_report.py`** — turns a batch of traces into the
  headline number the buildathon bar asks for: measured money recovered,
  broken down by scenario type and root cause, plus escalation/stop counts.

## Signal detection: from raw events, not pre-labeled fixtures

Earlier versions of this project had `Signal` objects arrive already
knowing their own category -- a payment_failure signal was just asserted
to be one. Nothing actually detected that a payment failed; it was
labeled that way by the data generator. `app/data/raw_events.py` now
generates a raw, unlabeled stream of Razorpay-style events instead --
`payment.failed`, `payment.captured`, `checkout.session.started`,
`subscription.charge.failed`, `invoice.created`, `invoice.paid` -- each
carrying a correlation id (order/checkout/mandate/invoice) and a
timestamp, but no signal category.

`app/engine/detection.py` is what turns that into `Signal` objects: it
groups events by their correlation id and checks whether a resolving
event ever showed up for that case (a `payment.captured` after a
`payment.failed`, an `invoice.paid` after an overdue `invoice.created`,
and so on). A case that resolved on its own -- the customer retried and
it went through, they came back and paid, the invoice got settled --
correctly produces **no signal at all**, the same way a real detection
system wouldn't raise an alert for a problem that already fixed itself.
For `overdue_receivable` specifically, an unresolved invoice only becomes
a signal once its due date has actually passed relative to the batch's
simulated "now" -- an invoice that isn't overdue yet produces nothing
either, regardless of whether it's been paid.

This means `generate_batch(n, seed)`'s `n` is the number of raw
event-cases simulated, not a guaranteed signal count -- a batch of 40
cases might detect 27 real signals and correctly drop 13 that resolved on
their own. `scripts/run_batch.py` prints both numbers
(`Detected X at-risk signal(s) from N raw event-case(s)`) so this
filtering is visible, not just asserted in a docstring. Diagnosis, policy,
and every playbook are unchanged by any of this -- they still only ever
consume a `Signal`, with the same `metadata` shape (`reason_code`,
`due_date`, `invoice_id`, `attempt_count`, `phone`, `email`) as before;
only *where a Signal comes from* changed, not what one looks like once it
exists.

## Mapping to the buildathon's example directions

| Example direction | Where it lives |
|---|---|
| Payment degradation → root cause → recovery action | Core engine + `payment_retry` playbook |
| Checkout drop-off recovery | `checkout_dropoff` playbook |
| Failed-subscription recovery | `subscription_mandate` playbook (staged retry sequencing) |
| B2B receivables chaser | `receivables_chaser` playbook |
| Mandate retry sequencer | Built into `subscription_mandate` (attempt-aware retry probability + `MAX_CONTACT_ATTEMPTS`) |
| Promise-to-pay tracker | `receivables_chaser` records the commitment; `pipeline.resolve_due_promises` judges it when the date arrives -- kept if a confirmed recovery exists, broken otherwise -- and a broken promise re-enters the batch and is escalated to a human by `policy.decide`. See "Promise-to-pay" below. |
| Hinglish voice recovery | Implemented as a **bilingual (Hindi/English) text-based recovery channel** (`app/playbooks/messaging_templates.py`) rather than live voice calls. Real-time speech (STT/TTS) was judged too time-risky to finish reliably in the buildathon window; a bilingual WhatsApp/SMS-style channel captures the same "meet the customer in their language" idea without that risk. |

## Compliant escalation and stopping rules

Two root causes (`bank_declined_risk`, `invoice_dispute`) are hard-coded to
always escalate to a human rather than auto-contact the customer, since
retrying or chasing in those cases is a compliance/trust risk, not a
recovery opportunity. Separately, any signal above
`HIGH_VALUE_ESCALATION_THRESHOLD` (default ₹50,000) is flagged for human
review rather than fully automated. Stopping rules cap total contact
attempts per customer, enforce a cooldown between attempts, respect quiet
hours, and honor opt-outs recorded in `opt_outs`.

## Audit trail

Every stage (`diagnosis`, `decision`, `ai_recommendation`, `decision_ai_refined`, `action`, `message_sent:<channel>`, `confirmation`)
is written to `audit_log.jsonl` (append-only, one JSON event per line) with
the full payload and reasoning, so any recovery decision can be traced back
to why it happened. Deliberately not SQLite -- see `app/db.py` for why.

## From simulated to real Razorpay test-mode

`app/integrations/razorpay_client.py` falls back to a mocked payment link
unless `USE_LIVE_RAZORPAY=true` *and* `RAZORPAY_KEY_ID`/`RAZORPAY_KEY_SECRET`
are set -- keys alone are not enough, so a batch run stays safely mocked by
default even if real test-mode keys are sitting in `.env`. With the flag
and keys both set, the same code path creates real Razorpay test-mode
payment links (`scripts/seed_test_data.py`), and `app/main.py` exposes a
`/webhook/razorpay` endpoint (HMAC-verified) to receive real payment-link
status updates and feed them back into the audit trail.

## AI recovery-decision agent

`app/engine/policy.py` is, and remains, the sole safety layer: every
compliance guardrail runs first and is fully deterministic, so it stays
simple, testable, and auditable independent of whether an LLM is
involved at all. `app/engine/agent.py` sits strictly downstream of it,
and only for a signal `policy.decide()` already cleared to proceed with
its assigned playbook (never one it stopped or escalated -- a
compliance-mandated outcome is never second-guessed by a model in either
direction).

For that narrower set of signals, when `USE_AI_RECOVERY_AGENT=true`,
Claude (`app/integrations/llm.py:llm_recommend_action`) is given the
signal's real context -- root cause, rule confidence, amount, assigned
playbook, prior contact attempts, language preference, and (where
relevant) mandate attempt count or invoice due date -- and must choose
exactly one of a fixed three-action set:

- `proceed` — agree with the deterministic call (the common case).
- `hold` — don't contact the customer this round.
- `escalate` — flag this specific case for human review, even though it
  didn't trip an automatic escalation rule.

The model cannot invent a fourth action, cannot change which playbook is
assigned, and cannot override a guardrail. `hold` and `escalate` map onto
the *same* `Decision.stop`/`Decision.escalate` fields the deterministic
guardrails use (with distinct `stop_reason`s -- `ai_recommended_hold` /
`ai_flagged_for_review` -- so they're never confused with a
cooldown/quiet-hours stop or a compliance escalation in the audit trail),
so `app/engine/actions.py` treats an AI-driven hold or escalation exactly
like any other one -- there's no separate, less-audited code path for AI
decisions. Every consultation, including a plain `proceed`, is logged as
its own `ai_recommendation` audit event; if it actually changed the
outcome, that's additionally logged as `decision_ai_refined`. On any
failure (bad key, network error, a response outside the bounded action
set) `llm_recommend_action` returns `proceed` with the failure recorded
in an `error` field, rather than raising -- so a flaky API call degrades
to the deterministic default and never blocks a batch.

Separately, `USE_LLM_DIAGNOSIS=true` still gates the older, narrower
low-confidence root-cause fallback in the same file. The synthetic
generator now occasionally (5% of signals) emits a reason code no rule
table recognizes specifically so that fallback path is actually reachable
in a normal demo batch, rather than only in a test that constructs a
Signal by hand.

## Performance: where a batch's time actually goes

Measured, not guessed: the entire deterministic pipeline -- detection,
diagnosis, policy, playbooks, confirmation, and all JSON state I/O --
processes 30 signals in **~0.25 seconds**. The AI agent is the entire other
cost. The Nemotron model is a reasoning variant: left to its default it runs
an internal "thinking" pass before answering, and for a bounded few-way
classification most of the generated tokens are that scratchpad rather than
the answer. Since generation is sequential, that pass dominates wall-clock
time -- measured directly, a single call took **~6.4s** with thinking on
versus **~0.9s** with it off, a ~7x difference. Issued one at a time, the
thinking-on path turned a large batch into minutes of waiting while the rest
of the system sat idle.

Two changes address it, both in a way that cannot weaken a guardrail:

1. **Suppress the thinking pass** (`app/integrations/llm.py`). The request
   sends `chat_template_kwargs.enable_thinking: false`, which NVIDIA's NIM
   API honors, so every consultation returns just the bounded answer with
   no scratchpad. (This has to sit at the top level of the request body --
   `extra_body` is an OpenAI-SDK client convenience, not a real API field,
   and sending it literally is a 400.)
2. **Issue consultations concurrently, ahead of the loop**
   (`pipeline.prefetch_agent_recommendations`). The pipeline itself stays
   strictly sequential, deliberately: the guardrails are order-dependent
   (cooldown and max-contact-attempts read contact history that earlier
   signals in the same batch write) and the JSON state store does unlocked
   read-modify-write, so parallelising the pipeline would both corrupt
   state and silently weaken compliance checks. Only the network waits move
   off the critical path.

The prefetch is speculative -- it picks who to ask using a provisional
decision computed before the batch has mutated any state. Correctness never
depends on that guess: each prefetched answer is stored with a fingerprint
of the exact context it was fetched for, and
`agent.refine_decision` uses it only if that fingerprint still matches the
context of the real decision. Anything stale is discarded and re-fetched
inline. Measured effect with a stubbed model at concurrency 6: 18
consultations, zero duplicate calls, 5.8x faster wall-clock than
sequential.

## What the agent decides, and what it can never decide

The agent's output widened from "should we proceed" to "how should we
recover", while the set of things it can influence stayed a closed list the
deterministic layer owns. It may:

- **choose the outreach channel**, from `PLAYBOOK_CHANNELS` in
  `app/engine/agent.py` -- the channels that playbook can actually deliver
  on. A channel outside that list is discarded and the playbook's own
  default is used, so a model naming `email` for a playbook that only does
  SMS/WhatsApp causes a normal send, not a broken one.

  This one was measured before it was trusted, and the first version failed
  that check. Given a free choice with no per-customer information, the model
  routed 24 of 26 English-preference customers to WhatsApp -- statistically
  identical to the Hindi ones -- while its stated reasoning cited a language
  preference it demonstrably wasn't acting on. That wasn't the model being
  lazy: it was being asked to discriminate between customers on evidence it
  had never been given, and a uniform answer is the rational response to
  that. Worse, the deterministic default it was overriding already varied by
  language, so the "smarter" layer was producing the *less* personalised
  outcome.

  The fix was to supply the missing evidence rather than to keep the claim:
  the context now carries `channels_already_tried` (from
  `db.get_channel_history` -- real attempts per channel, and how many led to
  a confirmed recovery), and the prompt instructs the agent to return `null`
  and let the language-aware default stand unless that history gives a
  concrete reason to switch. A channel override now means something happened
  before; on a first contact there is no override.
- **postpone the outreach** by 0-24 hours, when contacting immediately looks
  counterproductive for that specific case (a bank-side failure that needs
  time to clear before a retry has any chance).

Both are advisory, both are validated twice (in
`llm.llm_recommend_action` when parsing the response, and again in
`agent.refine_decision` against the playbook's own channel list), and both
are ignored entirely unless the action is `proceed` -- a `hold` or
`escalate` has no outreach to shape.

The delay is deliberately one-directional. `defer_hours` is clamped to
`max(0, min(n, 24))`, so the agent can push contact later but never bring it
forward -- a negative value can't be read as "contact sooner". And a
deferral is not a pre-authorisation: `app/engine/actions.py` persists the
whole signal (`db.record_deferred_signal`), and
`pipeline.release_due_deferrals` puts it back through the FULL pipeline when
its time comes -- diagnosis, every compliance guardrail, and the agent
again, evaluated against the later clock. A signal deferred into quiet hours
is simply stopped when it returns, exactly as a fresh signal would be. That
property is pinned by
`tests/test_deferral.py::test_a_signal_deferred_into_quiet_hours_is_stopped_not_sent`.

Storing the entire signal rather than just its id matters: synthetic batches
are regenerated per run, so an id-only deferral would be recorded and then
quietly never acted on -- a promise the system doesn't keep, which is the
exact class of claim the rest of this design exists to avoid.

## Promise-to-pay: a commitment the system actually follows up on

`receivables_chaser` sometimes records that a customer committed to paying by
a date. For a long time that was the whole feature: the promise was written
with `fulfilled: False` and then **nothing ever read it again** -- no
follow-up, nothing marking it kept or broken. A "tracker" that tracked
nothing, and one of the brief's own named directions.

`pipeline.resolve_due_promises` closes it. On the promised date, each pending
promise is judged against confirmed money -- `db.was_recovery_confirmed`
reads the same pending-recovery record the confirmation stage resolves, so
"kept" means the payment actually arrived, not merely that an outreach was
sent:

- **kept** -- logged as a `promise_kept` audit event; the case is closed and
  the customer is not contacted again.
- **broken** -- logged as `promise_broken`; the signal re-enters the batch
  carrying `promise_broken` in its metadata.

A broken promise is deliberately **not** another automated chase. A customer
who made an explicit commitment and missed it is a credit and relationship
judgement, not a reminder problem, so `policy.decide` escalates it to a human
(`stop_reason="broken_promise_to_pay"`), alongside the other compliance
guardrails and therefore before the AI layer is ever consulted. Nothing in
this feature gives the system a reason to contact anyone *more*.

The promise date is set from the batch's clock, not the wall clock -- with
`--simulate-time` a promise made on day 0 genuinely comes due on day 7, which
is the only way the follow-up is demonstrable at all.

Verified end to end on generated data: two promises made in a day-0 batch,
both unmet by day 8, both surfacing as `escalated` with
`plan: [diagnose:forgot, escalate:broken_promise_to_pay]` in a batch that was
fed no new signals at all -- and judged exactly once, so a later run does not
replay them.

## Recovery confirmation: a separate, audited step

A playbook (`app/playbooks/*.py`) never decides "recovered" for itself.
It only ever sends an outreach (payment link + message, or an invoice
reminder) and registers a *pending recovery* (`db.record_pending_recovery`)
carrying its own root-cause-aware probability estimate. Whether that
signal actually converts is decided entirely in
`app/engine/confirmation.py`, as its own pipeline stage that runs after
every signal in the batch has been sent, and is logged to the audit trail
as a distinct `"confirmation"` event -- separate from the `"action"` event
that recorded the send. This means a `RECOVERED` status is always
traceable to a specific confirmation event with its own timestamp, source,
and reference (a `payment_link_id` or `invoice_id`), not something baked
silently into the send itself.

There are two confirmation sources, both funneling through the same
`db.confirm_recovery()` call so the audit trail treats them identically:

- **`simulate_pending_confirmations()`** — the offline/demo path. Since we
  can't force a real customer to pay a real link within a hackathon
  timeline, this stands in for "the customer responded" by drawing once
  against the sending playbook's probability estimate, for every
  still-pending recovery in the batch. This is what runs by default
  (`app/engine/pipeline.py:process_batch()` calls it automatically after
  processing every signal).
- **`confirm_from_live_link_status()` / `reconcile_pending_recoveries()`** —
  the live *polling* path (`scripts/reconcile_recoveries.py`). A webhook
  needs a publicly reachable URL, which a laptop running a demo generally
  isn't, so without this a genuinely paid test-mode link would never make
  it back into the system. This asks Razorpay directly what happened to
  each unconfirmed link we created (via
  `razorpay_client.fetch_payment_link_status`) and resolves it through the
  same `db.confirm_recovery()` call, logged with
  `source="razorpay_link_poll"`. Mock links are skipped -- they have no
  upstream status.
- **`confirm_from_webhook()`** — the real push path, wired to
  `app/main.py`'s `/webhook/razorpay` endpoint. A genuine
  `payment_link.paid`/`.cancelled`/`.expired` Razorpay event (live
  test-mode only) is matched back to the signal that created that link via
  its `payment_link_id` reference, and resolves the same pending-recovery
  record the same way. Previously this endpoint verified and logged the
  webhook and then discarded it -- it never touched recovery state at all.
  Because confirming a recovery mutates money-recovered state, an unsigned
  request (no `RAZORPAY_WEBHOOK_SECRET` configured, so the signature check
  is skipped) is refused outright in live mode; unsigned requests stay
  accepted in mock mode only, so the endpoint remains curl-testable
  locally.

## What's simulated vs. real

Recovery *outcomes* (whether a customer actually pays after being
contacted) are simulated with root-cause-aware probabilities for the batch
demo, since we can't force real customers to respond within a hackathon
timeline -- but as of the confirmation-step design above, that simulation
happens at a distinct, audited "did this convert" boundary rather than
being folded into the playbook's own decision-making. The *mechanism* —
diagnosis, policy, payment link creation, messaging, confirmation
plumbing, audit logging — is real and runs the same way whether wired to
mocked or live Razorpay test-mode data; only the *source* of the
confirmation event (simulated vs. a real webhook) changes. This tradeoff
is called out explicitly in the pitch.
