# Backend — AI Revenue Recovery Agent

The engine, the API and the CLI tools. Paths below are relative to this
`backend/` folder. For the project overview and how to run the UI
alongside it, see the root `README.md`; the React frontend lives in
`../frontend/`.

An agent that detects revenue at risk (payment failures, checkout abandonment,
failed subscription mandates, overdue B2B receivables), diagnoses the root
cause, picks the right recovery playbook, executes a bounded recovery
workflow, and logs everything to an audit trail — then reports measured
money recovered across a batch.

## Quickstart

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env   # .env.example lives at the repo root; fill in your Razorpay test-mode keys
python scripts/run_batch.py --reset --n 80 --seed 7 --save-traces --simulate-time 2026-08-31T10:00:00
```

This generates 80 raw event-cases, runs them through detection (see
"Signal detection" below), and prints a recovery report -- no API keys
required yet, it falls back to mocked payment links. `--simulate-time`
fixes what "now" means for the quiet-hours check and the overdue-invoice
detection window (the real check is IST-aware and will correctly refuse
outreach at 2am IST — pass a daytime IST timestamp, e.g. 10:00 UTC = 15:30
IST, for a live demo). Example output:

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

`n` is how many raw event-cases go into detection, not a guaranteed
signal count -- some fraction always resolve on their own and correctly
produce no signal (a retried payment that went through, an invoice that
got paid). See "Signal detection" below.

A JSON copy of the report is written to `reports/latest_report.json`, and
the full audit trail (every diagnosis/decision/action, with reasoning) is
in `audit_log.jsonl` (one JSON event per line).

Inspect the reasoning behind any of it:

```bash
python scripts/inspect_audit.py --n 10             # last 10 audit events
python scripts/inspect_audit.py --signal-id <id>   # full trace for one signal
```

Or see the whole batch at once, in a browser:

```bash
python scripts/build_dashboard.py --open
```

That writes `reports/dashboard.html` -- one self-contained file, no server and no
network, so it works on conference wifi. Every case on it expands to the full
audit trail for that signal, read straight from `audit_log.jsonl`.

Run the test suite (engine, policy guardrails, playbooks, error handling):

```bash
pip install pytest   # if not already installed
pytest tests/ -v
```

## Wiring up the AI recovery-decision agent

Set `USE_AI_RECOVERY_AGENT=true` in `.env`, plus either a valid
`ANTHROPIC_API_KEY` (default, `LLM_PROVIDER=anthropic`, needs billing) or,
to run for free, `LLM_PROVIDER=nvidia` and a `NVIDIA_API_KEY` from
https://build.nvidia.com. That runs a free Nemotron model via NVIDIA's
hosted NIM API at roughly 40 requests/minute on the free tier (no billing
required); its internal reasoning pass is explicitly disabled per request,
since reasoning tokens otherwise dominate wall-clock time for a bounded
few-way classification (a ~7x per-call speedup, measured). Both providers go
through the same bounded prompt/response contract in
`app/integrations/llm.py` -- only which model answers changes.
This does not replace the deterministic diagnosis/policy engine -- rule-
based diagnosis and every compliance guardrail (opt-outs, mandatory
escalation, high-value thresholds, contact limits, cooldown, quiet hours)
still run first and are never touched by the agent. Instead, once a
signal has cleared every guardrail and is about to proceed with its
assigned playbook, Claude gets a second, narrower say: given the signal's
context (root cause, confidence, amount, prior contact attempts, etc.) it
can only choose `proceed` (agree with the deterministic call), `hold`
(don't contact this round), or `escalate` (flag for human review anyway)
-- it can never invent an action outside that set, and it can never
loosen a guardrail's stop/escalate. If the call fails or is disabled, it
silently falls back to `proceed` -- the deterministic default -- so the
batch is never blocked on a flaky API call.

Every consultation is logged to `audit_log.jsonl` as its own
`ai_recommendation` stage (with the model's raw action/confidence/
reasoning), separate from the deterministic `decision` stage, so you can
always see what the agent was asked, what it said, and whether it
actually changed the outcome:

```bash
python scripts/inspect_audit.py --n 20   # look for "stage": "ai_recommendation"
```

Beyond proceed/hold/escalate, the agent also shapes *how* the outreach
happens: it picks the channel (only from the ones that playbook actually
supports) and can postpone contact by up to 24 hours. A postponed signal is
persisted and re-enters a later batch, where every guardrail is evaluated
again against the later clock -- so deferring can delay contact but never
pre-authorise it. See "What the agent decides" in ../docs/architecture.md.

Note: with `USE_LLM_DIAGNOSIS=true` too, the synthetic generator
occasionally (5% of signals) produces a reason code no rule table
recognizes, so the low-confidence diagnosis fallback in
`app/integrations/llm.py:llm_diagnose` actually gets exercised in a
normal demo run rather than only in tests that construct a Signal by hand.

## Wiring up real Razorpay test-mode API calls

Once you've added `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` to `.env`:

```bash
python scripts/seed_test_data.py   # creates a few real test-mode payment links
```

Run the API layer (also handles Razorpay webhooks):

```bash
uvicorn app.main:app --reload
```

## Project layout

- `app/models.py` — core data types (Signal, Diagnosis, Decision, ActionResult,
  AgentRecommendation, Trace)
- `app/engine/` — the detect -> diagnose -> decide -> act -> confirm pipeline
  (`detection.py` for turning raw events into signals, `diagnosis.py`,
  `policy.py` for guardrails/stopping rules, `agent.py` for the optional AI
  recovery-decision layer, `actions.py` for dispatch + error handling,
  `confirmation.py` for turning a sent outreach into a confirmed recovery,
  `pipeline.py` for orchestration)
- `app/playbooks/` — one module per recovery scenario, plus bilingual message
  templates (the Hinglish text-based recovery channel)
- `app/integrations/` — Razorpay client (mocked until `USE_LIVE_RAZORPAY=true`
  and keys are set), messaging channel, LLM-assisted diagnosis fallback and
  the AI recovery-decision agent (both opt-in, both degrade safely if
  unconfigured or unreachable; Claude or free Nemotron, see `LLM_PROVIDER`)
- `app/data/raw_events.py` — generates a raw, unlabeled Razorpay-style event
  stream (no signal category attached); `app/data/synthetic_generator.py` is
  now a thin wrapper that runs it through `app/engine/detection.py`
- `app/reporting/` — batch-level "money recovered" reporting
- `app/db.py` — file-backed audit trail (JSONL), contact history, opt-outs,
  promise-to-pay tracking
- `scripts/run_batch.py` — main demo entry point
- `scripts/inspect_audit.py` — pretty-prints audit trail entries for a demo
- `scripts/seed_test_data.py` — creates real Razorpay test-mode payment links
- `scripts/reconcile_recoveries.py` — live-mode polling confirmation: asks
  Razorpay what happened to unconfirmed links (for when a webhook can't reach
  your machine)
- `scripts/system_metrics.py` — aggregate performance metrics from the audit trail
- `scripts/build_dashboard.py` — renders the latest batch as a self-contained
  `reports/dashboard.html` (no server, works offline): headline numbers, the
  detection funnel, recovery by scenario, what the AI agent did, and every case
  expandable to its complete audit trail
- `tests/` — pytest coverage for signal detection (resolved-vs-unresolved
  cases, overdue-invoice timing), diagnosis rules, policy guardrails
  (opt-outs, escalation, stopping rules, IST-aware quiet hours), playbooks,
  and full-batch pipeline resilience
- `../docs/architecture.md` — full design writeup for the submission
- `../docs/pitch_outline.md` — 5-minute pitch video script

See `../docs/architecture.md` for the full design rationale.
