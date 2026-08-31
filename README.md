# AI Revenue Recovery Agent (Razorpay Buildathon — Track 03)

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
cp .env.example .env   # then fill in your Razorpay test-mode keys
python scripts/run_batch.py --reset --n 80 --seed 7 --save-traces --simulate-time 2026-08-31T10:00:00
```

This runs a full synthetic batch through the engine end-to-end (no API keys
required yet — it falls back to mocked payment links) and prints a recovery
report. `--simulate-time` fixes what "now" means for the quiet-hours check
(the real check is IST-aware and will correctly refuse outreach at 2am IST —
pass a daytime IST timestamp, e.g. 10:00 UTC = 15:30 IST, for a live demo).
Example output:

```
Batch size: 80
Total at risk: Rs. 23,87,220.71
Total recovered: Rs. 5,12,402.24
Recovery rate: 21.5%
Action outcomes: {'sent': 40, 'recovered': 28, 'stopped': 10, 'escalated': 2}
```

A JSON copy of the report is written to `reports/latest_report.json`, and
the full audit trail (every diagnosis/decision/action, with reasoning) is
in `audit_log.jsonl` (one JSON event per line).

Inspect the reasoning behind any of it:

```bash
python scripts/inspect_audit.py --n 10             # last 10 audit events
python scripts/inspect_audit.py --signal-id <id>   # full trace for one signal
```

Run the test suite (engine, policy guardrails, playbooks, error handling):

```bash
pip install pytest   # if not already installed
pytest tests/ -v
```

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

- `app/models.py` — core data types (Signal, Diagnosis, Decision, ActionResult)
- `app/engine/` — the detect -> diagnose -> decide -> act pipeline (`diagnosis.py`,
  `policy.py` for guardrails/stopping rules, `actions.py` for dispatch + error
  handling, `pipeline.py` for orchestration)
- `app/playbooks/` — one module per recovery scenario, plus bilingual message
  templates (the Hinglish text-based recovery channel)
- `app/integrations/` — Razorpay client (mocked until keys are set), messaging
  channel, optional LLM-assisted diagnosis fallback
- `app/data/synthetic_generator.py` — generates realistic test batches
- `app/reporting/` — batch-level "money recovered" reporting
- `app/db.py` — file-backed audit trail (JSONL), contact history, opt-outs,
  promise-to-pay tracking
- `scripts/run_batch.py` — main demo entry point
- `scripts/inspect_audit.py` — pretty-prints audit trail entries for a demo
- `scripts/seed_test_data.py` — creates real Razorpay test-mode payment links
- `tests/` — pytest coverage for diagnosis rules, policy guardrails
  (opt-outs, escalation, stopping rules, IST-aware quiet hours), playbooks,
  and full-batch pipeline resilience
- `docs/architecture.md` — full design writeup for the submission
- `docs/pitch_outline.md` — 5-minute pitch video script

See `docs/architecture.md` for the full design rationale.
