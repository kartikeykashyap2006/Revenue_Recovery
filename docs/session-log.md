# Recoup — Engineering Log

**Razorpay Buildathon, Track 03.** A session changelog followed by a from-source
architecture walkthrough of the AI Revenue Recovery Agent and its frontend, Recoup.

At time of writing: 76 backend tests passing, 17 commits with corrected authorship,
3 real bugs found and fixed, 3 frontend pages (Overview / Cases / Agent).

---

## 1. Session summary

Five phases, in the order they happened.

### Phase 1 — Verify, then plan

Read `CLAUDE.md` and `docs/architecture.md`, then ran the suite and a live batch
rather than trusting the docs at face value.

- 74/74 tests passing; a live batch confirmed real model calls and correct
  detection filtering (7 of 20 raw cases resolved on their own, no signal needed)
- Identified the actual weak point: `docs/pitch_outline.md` — the literal demo
  script — described already-shipped features as "what's next," and cited a
  stale test count

### Phase 2 — Make the existing frontend actually functional

Before any redesign, closed the gap between "renders a batch" and "lets you
drive the engine": a new `/api/config` endpoint, seed/simulate-time run
controls, and search/filter/pagination on the case list.

- Fixed a quiet correctness bug in `AgentPanel`: it inferred "AI agent is off"
  from zero consultations — indistinguishable from "on, but no signal cleared
  every guardrail this run"

Files: `backend/app/main.py`, `frontend/src/api.ts`, `frontend/src/components/CaseList.tsx`

### Phase 3 — Rebuild it as a real product: Recoup

Replaced the single-scroll page with routed pages sharing state through a
context provider, and gave it a visual system and a name.

- **Overview** — headline stats, detection funnel, recovery by scenario
- **Cases** — every signal, searchable and filterable, full audit trail one
  click away
- **Agent** — every case the AI actually changed, with its real `reasoning`
  string quoted

Added: `react-router-dom`, `context/DashboardContext.tsx`,
`layout/{AppShell,Sidebar,TopBar}.tsx`, `pages/{Overview,Cases,Agent}.tsx`

### Phase 4 — Test it hard, fix what broke

An audit of every CLI-vs-API code path turned up the highest-value bug in this
session: the API had silently diverged from the CLI it was meant to mirror.

1. **Batch-detection marker never logged by the API.** `scripts/run_batch.py`
   logged a `batch_detection` event after every run; `/api/run-batch` never
   did. Every click of "Run batch" in the UI was silently folding its results
   into whatever the last CLI run had logged — "Needed a signal: 13" stayed
   frozen for hours while "Contacted: 105" kept climbing. This is what produced
   the 8.9% recovery-rate question mid-session.
2. **Malformed `simulate_time` crashed with a raw 500.** Now a clean `400`
   with the bad value quoted back.
3. **A dead backend showed a bare `failed: 502`.** Vite's dev proxy returns a
   gateway error rather than letting `fetch()` throw, so the frontend's
   purpose-built "could not reach the backend" message never fired. Fixed in
   `api.ts`.

Added `backend/tests/test_api.py` as a permanent regression test for the
first two. Re-verified existing coverage for the invariants that matter most
(negative-delay clamping, the AI agent never consulted on an already-stopped
decision) rather than re-deriving them from scratch.

### Phase 5 — Ship it

Repointed `origin` to `github.com/kartikeykashyap2006/Revenue_Recovery`,
committed everything, and pushed.

- Corrected commit authorship: the placeholder `kartikey@example.com` was
  replaced across all 17 commits, then force-pushed — the author *name* was
  already right, the email just didn't link to a GitHub account
- Fixed both READMEs: a broken `cp .env.example .env` path (the file lives at
  the repo root, not inside `backend/`), broken `docs/…` links from inside
  `backend/README.md`, and the same staleness the pitch outline had — old
  test count, no mention of Recoup or its three pages

---

## 2. Architecture

One engine, four playbooks, an optional and strictly bounded AI layer.
Revenue leaks out of a payments business through several doors at once — a
card payment degrades, a checkout gets abandoned, a subscription mandate
stops working, an invoice goes unpaid. Recoup's backend treats these as one
shape (detect → diagnose → decide → act → confirm) applied to four signal
types, rather than four separate bots. The deterministic policy layer is the
only component allowed to say *no*; an optional AI layer sits strictly
downstream of it and can only ever add caution, never remove it.

### 2.1 The recovery pipeline

```
Raw events (unlabeled)
        │
        ▼
     Detect  ── drops cases that resolved on their own
        │
        ▼
    Diagnose  ── deterministic root-cause rule tables
        │
        ▼
     Decide  ── every compliance guardrail, before any contact
        │
        ├── stop / escalate ───────────► Human review (AI never consulted)
        │
        ▼ cleared
    AI agent  ── optional, bounded: proceed / hold / escalate
        │
        ├── hold / escalate ───────────► Human review (same outcome, different door)
        │
        ▼ proceed
       Act  ── sends, status = sent, registers a pending recovery
        │
        ▼
     Confirm  ── separate, later, separately-audited stage → RECOVERED or not

Every stage above appends its own event to audit_log.jsonl,
which is the only thing /api/dashboard reads to build every number shown.
```

The only branch point is **Decide**: a signal a guardrail stops or escalates
never reaches the AI agent at all. A signal the agent itself holds or
escalates lands in the same human-review outcome through a different door.

| Stage | What happens |
|---|---|
| **detect** | `app/data/raw_events.py` generates Razorpay-style events (`payment.failed`, `checkout.session.started`, …) with no signal category attached. `app/engine/detection.py` groups them by correlation id and raises a signal only if the case never resolved on its own. |
| **diagnose** | `app/engine/diagnosis.py` maps failure/reason codes to root causes via rule tables, with an LLM fallback (`USE_LLM_DIAGNOSIS`) only for low-confidence, unmatched codes. |
| **decide** | `app/engine/policy.py` — the sole safety layer, fully deterministic. Runs opt-outs, mandatory-human root causes (`bank_declined_risk`, `invoice_dispute`), the ₹50,000 high-value threshold, max-contact-attempts, a cooldown window, and IST-aware quiet hours. |
| **agent** (optional) | `app/engine/agent.py` gets one bounded call per cleared signal: `proceed`, `hold`, or `escalate`, plus an optional channel override and a 0–24h defer. Cannot invent a fourth action, loosen a guardrail, or move contact sooner — a negative `defer_hours` clamps to zero. |
| **act** | One playbook per scenario in `app/playbooks/` sends a payment link and a message (English or Hinglish) and calls `db.record_pending_recovery` — never marks anything recovered itself. |
| **confirm** | `app/engine/confirmation.py` is the only place a `RECOVERED` status gets written — via a simulated gateway draw by default, or a real Razorpay webhook / polled link status in live mode. |

### 2.2 Backend modules

Python, FastAPI, 81 tests. The CLI (`scripts/`) and the API (`app/main.py`)
both call into the same `app/engine/pipeline.py` — the two surfaces cannot
diverge in behavior, only in how they're invoked.

| Path | Role |
|---|---|
| `app/models.py` | Shared vocabulary — Signal, Diagnosis, Decision, ActionResult, AgentRecommendation, Trace |
| `app/engine/pipeline.py` | Orchestration: `process_batch`, deferral release, promise resolution, agent prefetch |
| `app/engine/policy.py` | Every compliance guardrail — the one component allowed to say no |
| `app/engine/agent.py` | Bounded AI layer; builds context, validates the model's response against the closed action set |
| `app/integrations/llm.py` | Claude or Nemotron via `LLM_PROVIDER`; every failure degrades to the deterministic default |
| `app/db.py` | File-backed audit trail (`audit_log.jsonl`) + contact history, opt-outs, promise tracker (`state.json`) |
| `app/reporting/dashboard_data.py` | The one computation of "what happened" — read by `/api/dashboard` and the offline HTML alike |
| `app/main.py` | FastAPI surface: `/api/run-batch`, `/api/dashboard`, `/api/config`, `/webhook/razorpay` |
| `scripts/run_batch.py` | CLI entry point — same pipeline, human-readable progress output |
| `scripts/build_dashboard.py` | Renders `dashboard_data`'s payload to one offline HTML file, no server needed |

### 2.3 Recoup — the frontend

TypeScript + React + Vite, routed with `react-router-dom`. Everything on
screen is read from the same `/api/dashboard` payload the offline HTML
dashboard renders — there is exactly one computation of any given number.

- **Overview** — revenue at risk, confirmed recovered, recovery rate, the
  detection funnel, recovery by scenario type
- **Cases** — every case in the latest batch; search by customer or signal
  id, filter by outcome/scenario/"AI changed this", paginated 25 at a time;
  any row expands to its complete audit trail
- **Agent** — consultation stats plus a card per case the AI actually
  overrode, quoting its real `reasoning` string, stated confidence, and
  channel choice
- **Top bar, everywhere** — batch size, an expandable seed / simulate-time
  panel for reproducing a specific run, and a live "AI agent on · `<provider>`"
  status read from `/api/config`, not inferred from a batch's own results

---

## 3. Real vs. simulated

Stated plainly, the way `CLAUDE.md` insists on — a bug caught by measuring,
not trusting.

**Real, end to end:**
- Detection, diagnosis, every compliance guardrail
- The AI agent's model calls (Nemotron/Claude), bounded action set, and audit trail
- Razorpay payment-link creation, in live mode with test-mode keys
- Webhook signature verification (HMAC), including live-mode refusal when unsigned
- The audit log, and every number derived from it

**Simulated by default:**
- Outbound messaging — no SMS/WhatsApp/email provider is wired in
- Whether the customer actually pays — drawn from a root-cause-aware
  probability unless a real webhook or link-status poll drives the same
  confirmation code path
- Hinglish is a bilingual *text* channel — not voice

---

## 4. Invariants

The design, not preferences — each one written down in `CLAUDE.md` because
violating it has already shipped a bug once.

1. **The AI agent may only add caution.** It can turn a proceed into hold or
   escalate, pick a channel from the playbook's own list, or postpone
   outreach — never loosen a guardrail, invent an action, or move contact
   sooner.
2. **Playbooks never decide "recovered."** Only the confirmation stage does,
   as its own audited event — reading money off an `action` event returns
   zero forever by construction.
3. **One clock.** Anything time-based takes `now_utc` and falls back to the
   wall clock only with no batch clock. Mixing the two has caused three real
   bugs in this project's history.
4. **The pipeline stays sequential.** Guardrails are order-dependent
   (cooldown reads contact history earlier signals write); only the AI
   agent's network calls are made concurrent, by prefetching — never by
   parallelising the pipeline itself.
5. **Never record something nothing acts on.** Deferrals and promises-to-pay
   were both once write-only. Both now have a resolution path — this
   session's bug (§1, Phase 4) was a variant of the same failure: a marker
   written by one caller and silently never read by another.
6. **One computation per number.** `app/reporting/dashboard_data.py` is the
   only place the dashboard payload is built — the API and the offline HTML
   both render it, never recompute it.

---

*Recoup · AI Revenue Recovery Agent · Razorpay Buildathon Track 03 ·
github.com/kartikeykashyap2006/Revenue_Recovery*
