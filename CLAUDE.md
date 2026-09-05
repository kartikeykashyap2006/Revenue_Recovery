# AI Revenue Recovery Agent — working notes

Razorpay Buildathon Track 03. Detects revenue at risk, diagnoses it, picks a
bounded recovery action, executes it, and proves what money actually came back.

`backend/` is Python (engine, FastAPI, CLI, 81 tests). `frontend/` is
TypeScript + React (Vite) — a named product, "Recoup", with its own 42-test
Vitest suite. They share only an HTTP contract.

## Running things

```bash
cd backend && uvicorn app.main:app --reload     # :8000
cd frontend && npm run dev                      # :5173, proxies /api to :8000

cd backend
pytest tests/ -q
python scripts/run_batch.py --reset --n 25 --seed 7 --simulate-time 2026-08-31T10:00:00
python scripts/system_metrics.py
python scripts/build_dashboard.py --open        # offline HTML, same data as the UI

cd frontend && npm test                         # Vitest + RTL, 42 tests
```

State lives beside the code it belongs to: `backend/audit_log.jsonl` and
`backend/state.json`, both relative to the CWD — run backend commands from
`backend/`. That relative-path behaviour is load-bearing: `tests/conftest.py`
isolates each test with `monkeypatch.chdir(tmp_path)`. Don't "fix" it by
anchoring paths to the project root.

## Invariants — these are the design, not preferences

**The AI agent may only add caution.** It can turn a proceed into hold or
escalate, pick a channel from the playbook's own list, or postpone outreach.
It can never loosen a guardrail, invent an action outside its bounded set,
change the playbook, or cause contact *sooner* (`defer_hours` is clamped to
`max(0, min(n, 24))`). It is never consulted for a decision the deterministic
guardrails already stopped or escalated. Every consultation is audited even
when it changes nothing.

**Playbooks never decide "recovered".** They send and register a pending
recovery; only `app/engine/confirmation.py` produces a RECOVERED outcome, as
its own audited stage. Reading `amount_recovered` off an `action` audit event
gives zero forever — the action is logged before confirmation runs.

**One clock.** Anything time-based takes `now_utc` and falls back to
`datetime.utcnow()` only when there's no batch clock. Mixing the two has
caused three real bugs here (cooldown couldn't expire under `--simulate-time`;
the agent called overdue invoices "in the future"; promises never came due).
If you add a time-based rule, thread the clock.

**The pipeline stays sequential.** Guardrails are order-dependent (cooldown and
max-attempts read contact history earlier signals write) and the JSON store
does unlocked read-modify-write. Model calls are made concurrent by
*prefetching* them (`pipeline.prefetch_agent_recommendations`) and reusing them
behind a context fingerprint — never by parallelising the pipeline itself.

**NVIDIA NIM signals congestion with 503, not 429.** The shared free-tier
worker returns `503 ResourceExhausted` when it's full; treating only 429 as
backpressure let the adaptive throttle retry straight back into a saturated
worker, measured turning a 40 RPM pace into ~26 RPM effective. Both codes
must widen `llm.py`'s request interval. If you touch the NVIDIA retry path,
keep them together.

**Never record something nothing acts on.** Deferrals and promises-to-pay were
both once written and never read. If you persist an intention, also build the
path that resolves it, or don't persist it.

**One computation per number.** `app/reporting/dashboard_data.py` builds the
dashboard payload; the API and the offline HTML both render it. Don't
recompute totals in a second place.

**Every LLM path degrades safely.** A failure returns the deterministic default
with the error recorded, never an exception that breaks a batch.

## Testing conventions

Tests pin behaviour and invariants, not implementation. Several exist
specifically because a bug shipped: read the docstrings before changing one.

`tests/conftest.py` blanks credentials and feature flags because `app/config.py`
reads `.env` at import time. **Any new flag that costs money or hits the network
must be blanked there**, or the suite will fire real API calls.

## Known gaps — real, and deliberately not fixed

Fine for a demo, not for production, and worth saying plainly rather than
discovering under questioning:

- `app/db.py` does unlocked read-modify-write on a JSON file. Two concurrent
  webhooks can lose a write. Single-process batches are unaffected.
- No auth on the API. `/api/run-batch` burns quota; `/audit-log` returns
  customer names, phones and emails; `/api/reset` wipes the audit trail and
  all accumulated state for anyone who can reach it.
- Every `db` call re-reads and rewrites the whole state file — fine at demo
  size, quadratic beyond it.
- Contact details are written to the audit log in plaintext.
- Outbound messaging is simulated; recovery confirmation is simulated by
  default (a real Razorpay webhook drives the same code path).
- Hinglish is a bilingual **text** channel, not voice. Don't claim voice.

## Where the reasoning lives

`docs/architecture.md` explains why each design choice was made, including the
bugs that motivated them. Commit messages carry the same reasoning — `git log`
is genuinely useful here.
