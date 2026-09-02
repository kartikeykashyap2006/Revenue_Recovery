# AI Revenue Recovery Agent

**Razorpay Buildathon — Track 03**

Detects revenue at risk (payment failures, checkout abandonment, failed
subscription mandates, overdue B2B receivables), diagnoses why, chooses a
bounded recovery action, executes it, and proves what money actually came
back — with compliant escalation, stopping rules, and a complete audit trail.

```
razorpayproject/
├── backend/     Python — the engine, the API, the tests, the CLI tools
│   ├── app/         detection → diagnosis → policy → AI agent → playbooks → confirmation
│   ├── scripts/     run a batch, inspect the audit trail, metrics, offline dashboard
│   └── tests/       74 tests
├── frontend/    TypeScript + React (Vite) — the dashboard UI
│   └── src/         typed API client, components, audit-trail viewer
└── docs/        architecture writeup and pitch outline
```

The two halves share nothing but an HTTP contract. The backend computes the
dashboard payload once (`backend/app/reporting/dashboard_data.py`) and serves
it at `/api/dashboard`; the frontend consumes it through a typed client
(`frontend/src/types.ts`), so a backend change that breaks the contract shows
up as a TypeScript error rather than as `undefined` on the page.

## Run it

Two terminals.

**Backend** (Python 3.9+):

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # optional — it runs fully without any keys
uvicorn app.main:app --reload # http://127.0.0.1:8000
```

**Frontend** (Node 18+):

```bash
cd frontend
npm install
npm run dev                   # http://localhost:5173
```

Open http://localhost:5173 and press **Run batch**. The dev server proxies
`/api` to the backend, so there is no CORS to configure.

### Without the frontend

The engine is a CLI tool first; the UI is a view onto it.

```bash
cd backend
python scripts/run_batch.py --reset --n 25 --seed 7 --simulate-time 2026-08-31T10:00:00
python scripts/system_metrics.py          # aggregate performance from the audit trail
python scripts/build_dashboard.py --open  # same dashboard as one offline HTML file
python scripts/inspect_audit.py --signal-id <id>   # one signal's full trace
pytest tests/ -v
```

`build_dashboard.py` renders from the *same* payload function the API serves,
so the offline file and the React app can never disagree about a run — useful
when the venue wifi isn't.

## What it does, in order

1. **Detect** — a raw, unlabeled event stream (`payment.failed`,
   `checkout.session.started`, `invoice.created`, …) is correlated by case, and
   a signal is raised only for a case that never resolved on its own. A batch
   of 25 raw cases typically yields ~16 real signals; the rest fixed themselves
   and messaging them would be wrong.
2. **Diagnose** — deterministic rule tables map failure codes to root causes,
   with an optional LLM fallback for codes no rule recognises.
3. **Decide** — every compliance guardrail runs *before* any contact: opt-outs,
   root causes that must go to a human, per-type high-value thresholds,
   max-contact-attempts, cooldown, IST-aware quiet hours, and broken
   promises-to-pay.
4. **Refine (optional AI)** — for signals that cleared every guardrail, a
   bounded agent may add caution (`proceed`/`hold`/`escalate`) and shape the
   outreach (channel, or postponing it). It can never loosen a guardrail,
   invent an action, or contact anyone sooner.
5. **Act** — one playbook per scenario sends a payment link and a message, in
   English or Hinglish.
6. **Confirm** — a playbook never decides "recovered" for itself. A separate,
   separately-audited confirmation stage does, driven by a simulated gateway,
   a real Razorpay webhook, or polling link status.

Every stage of every signal is appended to `backend/audit_log.jsonl`, and any
case in the UI expands to its full trail.

## Configuration

Everything runs with no keys at all (mocked payment links, AI layer off). To
switch parts on, copy `backend/.env.example` to `backend/.env`:

| Setting | Effect |
|---|---|
| `USE_AI_RECOVERY_AGENT=true` | turns on the bounded AI decision layer |
| `LLM_PROVIDER=gemini` + `GEMINI_API_KEY` | free Gemma via Google AI Studio |
| `LLM_PROVIDER=anthropic` + `ANTHROPIC_API_KEY` | Claude instead |
| `USE_LIVE_RAZORPAY=true` + test keys | real test-mode payment links |
| `AI_AGENT_MAX_CONCURRENCY` | agent calls issued in parallel (default 6) |

## Honest scope

- Outbound messaging is simulated — there is no SMS/WhatsApp/email provider
  wired in; the audit trail records exactly what would have been sent.
- Recovery confirmation is simulated by default. The mechanism is real and a
  live Razorpay webhook drives the same code path; only the *source* of the
  confirmation event changes.
- Hinglish is a bilingual **text** channel, not voice.
- The JSON state store suits a single-process demo. Real deployment would want
  Postgres, auth on the API, and a job queue — see `docs/architecture.md`.

Full design writeup: `docs/architecture.md`. Pitch script: `docs/pitch_outline.md`.
