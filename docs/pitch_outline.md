# 5-Minute Pitch Outline

## Demo command (use this exact one for a reproducible, representative run)

```bash
python scripts/run_batch.py --reset --n 80 --seed 7 --save-traces --simulate-time 2026-08-31T10:00:00
```

This seed/size combination reliably shows recovery and escalation across
all four scenario types in one run (re-run this exact command yourself
before presenting -- exact numbers will differ slightly from below since
recovery is confirmed via a genuinely random draw, see "Confirmation
phase" below):

```
Detected 51 at-risk signal(s) from 80 raw event-case(s) (29 resolved on
their own -- no signal needed).
...
Batch size: 51
Total at risk: Rs. 22,11,727.98
Total recovered: Rs. 3,22,813.94
Recovery rate: 14.6%
Action outcomes: {'recovered': 16, 'sent': 26, 'escalated': 9}
```

The first line is worth calling out explicitly on camera: 80 is the
number of raw event-cases fed into detection, not the batch size --
detection genuinely dropped 29 of them because their own event history
(a retried payment that went through, a customer who came back and paid)
shows they never needed a recovery signal in the first place. See
"Signal detection" in section 5 below.

Note there's no `stopped` in this particular run -- with `--reset` and a
single fresh batch of mostly-distinct customers, the only stopping rules
that can actually fire are cooldown and max-contact-attempts (both need
repeat contact with the same customer, which a single one-shot batch
rarely produces) and opt-outs (nothing in this batch opts out). Quiet
hours is deliberately bypassed by `--simulate-time`. If you want to show a
`stopped` case live, run the batch twice in a row *without* `--reset` on
the same seed -- the second pass's repeat contacts will trigger cooldown.

`--simulate-time` controls what "now" means for every time-based check --
quiet hours and the cooldown between attempts -- so the demo isn't at the
mercy of what time you happen to be recording, and so the passage of days is
demonstrable. Every other guardrail (opt-outs, escalation, max-contact) is
time-independent and runs identically either way. To show cooldown live: run
the same batch twice a simulated day apart (both send), then a third time a
few hours later (stopped on cooldown).

## 1. Problem (30s)

Revenue leaks through payment failures, checkout drop-off, failed
subscriptions, and overdue invoices — each looks different on the surface,
but shares the same shape: detect, diagnose, recover.

## 2. Live demo (2.5 min)

Have **Recoup** (the product name for the frontend) open in a browser tab
before you start (`cd backend && uvicorn app.main:app --reload`,
`cd frontend && npm run dev`, open http://localhost:5173). It's a real
multi-page app -- sidebar nav across **Overview**, **Cases**, and **Agent** --
not a single scrolling report. Click **Run batch** on camera (the control is
in the top bar on every page) -- this fires `/api/run-batch`, which runs the
exact same pipeline as the CLI (raw event generation, detection, diagnosis,
policy, the AI agent, confirmation) and returns the same numbers
`dashboard_data.py` computes for every other surface. Watching the button
trigger real model calls and come back with a populated dashboard a few
seconds later is the strongest "this is really running, not a slideshow"
moment available -- better than reading numbers off a pre-built file.

**Overview** has the headline numbers, the detection funnel, and recovery by
scenario. **Cases** is the centrepiece: every case in the batch, searchable
and filterable by outcome/scenario, where any row expands to that signal's
entire audit trail. Expanding one case is the strongest single moment in the
demo -- it turns "we log every decision" from a claim into something the
judges watch you click. **Agent** is the direct answer to "is the AI actually
deciding anything": it surfaces every case where the model's call changed the
deterministic outcome, with its actual `reasoning` string quoted on screen --
see section 4 below.

(`reports/dashboard.html`, built with `python scripts/build_dashboard.py`, is
the offline fallback -- same payload, no server needed, useful if venue wifi
makes running two local dev servers risky. Keep it open in a second tab as a
backup, not the headline.)

For the version of this demo run from the CLI instead, use the command at the
top of this file. Point out the two visibly distinct phases as they happen:
every signal is processed and sent first (all show `-> sent`), then a
separate "Simulating gateway confirmations for N pending payment(s)..."
phase runs and *that's* when recovered amounts appear -- this is deliberate,
not cosmetic: a playbook never decides "recovered" for itself (see
`app/engine/confirmation.py`), so every `RECOVERED` result in the report is
traceable to a distinct `confirmation` audit event with its own timestamp
and reference, separate from the `action` event that recorded the send.

Walk through one trace end-to-end using
`python scripts/inspect_audit.py --signal-id <id>` on a recovered payment
signal from `reports/traces.json`: a payment failure -> diagnosed as
`card_expired` -> `payment_retry` playbook -> payment link sent (`action`,
status `sent`) -> gateway confirmation event (`confirmation`, status
`recovered`). Show the printed batch report (total at risk, total
recovered, recovery rate, breakdown by scenario type).

## 3. Compliance & guardrails (1 min)

Worth one line on promise-to-pay, since it shows the system keeping track of
something over time rather than within a single batch: when a customer commits
to a date, run the batch again after that date with `--simulate-time` and the
unmet promise comes back on its own and is escalated to a human -- a broken
commitment buys a person, never another automated chase.

Pull one `escalated` trace (an `invoice_dispute` or a high-value signal)
and one `stopped` trace (cooldown/quiet-hours/opt-out) from
`reports/traces.json`, and show their audit entries with
`python scripts/inspect_audit.py --signal-id <id>`. This is the "compliant
escalation, stopping rules, and an audit trail" the brief asks for, made
concrete on screen.

## 4. Where the AI actually is (45s)

Set `USE_AI_RECOVERY_AGENT=true` before recording, with either
`ANTHROPIC_API_KEY` set (default, `LLM_PROVIDER=anthropic`, needs
billing) or `LLM_PROVIDER=nvidia` plus a free `NVIDIA_API_KEY` from
https://build.nvidia.com -- same prompts, same bounded action set, either
way (`app/integrations/llm.py`). This is the direct answer to
"is an LLM actually deciding anything, or is this all if/else": for every
signal that clears the deterministic policy engine's guardrails and is
about to proceed with its assigned playbook, the model gets one narrow,
bounded call -- `proceed`, `hold`, or `escalate` -- given the signal's
real context. It can add caution but can never loosen a guardrail or
invent a fourth action. Fastest way to show this live: Recoup's **Agent**
page lists exactly the cases where a consultation changed the outcome, each
with its `reasoning` string already quoted -- no CLI needed. Or pull up an
`ai_recommendation` audit event with
`python scripts/inspect_audit.py --n 20` and read the model's actual
`reasoning` string out loud -- that's the concrete evidence there's a real
model call happening, not a hardcoded label. If a signal's `decision_ai_
refined` event shows a `hold` or `escalate`, walk through that one:
compare its deterministic `decision` event (says proceed) against the
`ai_recommendation` event right after it (says hold/escalate, with the
model's own stated reason) to show the AI genuinely changed the outcome,
not just annotated it. `app/engine/agent.py` has the full bounded-action
design; if no key is configured, the whole system still runs identically
minus this layer -- it's additive, never load-bearing.

The agent also decides *how* to recover, not just whether: it can switch the
outreach channel (only from what that playbook can actually deliver, and only
when this customer's own contact history gives a reason -- on a first contact
it declines and the language-aware default stands) and can postpone contact by
up to 24 hours when now looks like the wrong moment. Show
a trace whose plan reads
`[diagnose:technical_glitch, execute:checkout_dropoff, ai_agent:proceed, ai_channel:whatsapp]`
-- the deterministic engine picked the playbook, the model picked the channel.
For the strongest version, show a `deferred` signal in one run, then re-run
with `--simulate-time` a few hours later and watch the same signal come back,
get re-checked against every guardrail, and go out. Deferring can only ever
delay contact: a signal postponed into quiet hours is stopped when it returns.

## 5. Architecture (45s)

**Signal detection** (`app/data/raw_events.py` + `app/engine/detection.py`)
starts from an unlabeled raw event stream -- `payment.failed`,
`payment.captured`, `checkout.session.started`,
`subscription.charge.failed`, `invoice.created`, `invoice.paid` -- and
only emits a `Signal` for a case that never resolved on its own, which is
why 80 raw cases became 51 signals above. One engine, pluggable playbooks
(`app/playbooks/`), real Razorpay test-mode integration via
`payment_link.create` (mocked by default; set `USE_LIVE_RAZORPAY=true`
plus test-mode keys to switch to real payment links — same code path
either way), a separate confirmation stage
(`app/engine/confirmation.py`) that a real Razorpay webhook can drive
instead of the simulated demo path, an AI recovery-decision agent
(`app/engine/agent.py`, Claude or free Nemotron) that can only add caution
downstream of the deterministic policy engine, and 81 passing tests
covering signal detection, diagnosis rules, policy guardrails, playbook
mechanics, the confirmation step, the AI agent's bounded behavior,
deferral, promise-to-pay, the API's own batch-detection bookkeeping, and
crash resilience (`pytest tests/ -v`).

A TypeScript/React frontend (`frontend/`) talks to FastAPI over `/api` and
renders the same payload `app/reporting/dashboard_data.py` builds for the
offline HTML dashboard -- one computation, three surfaces (CLI report, API,
UI) that can never disagree about a number.

## 6. What's next (15s)

No auth on the API and no locking on the JSON state store -- both fine at
demo scale, both real work before this touches production traffic; richer
detection rules (e.g. distinguishing a slow retry from an abandoned one by
elapsed time, not just event presence); automated tests for the frontend to
match the backend's 74.
