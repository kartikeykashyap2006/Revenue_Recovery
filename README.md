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
python scripts/run_batch.py --reset --n 80 --seed 7 --save-traces
```

This runs a full synthetic batch through the engine end-to-end (no API keys
required yet — it falls back to mocked payment links) and prints a recovery
report, e.g.:

```
Batch size: 60
Total at risk: Rs. 4,32,110.00
Total recovered: Rs. 1,18,450.00
Recovery rate: 27.4%
```

A JSON copy of the report is written to `reports/latest_report.json`, and
the full audit trail (every diagnosis/decision/action, with reasoning) is
in `audit_log.jsonl` (one JSON event per line).

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
- `app/engine/` — the detect -> diagnose -> decide -> act pipeline
- `app/playbooks/` — one module per recovery scenario
- `app/integrations/` — Razorpay client, messaging channel, optional LLM diagnosis
- `app/data/synthetic_generator.py` — generates realistic test batches
- `app/reporting/` — batch-level "money recovered" reporting
- `app/db.py` — file-backed audit trail (JSONL), contact history, opt-outs, promise-to-pay tracking
- `scripts/run_batch.py` — main demo entry point
- `docs/architecture.md` — full design writeup for the submission

See `docs/architecture.md` for the full design rationale.
