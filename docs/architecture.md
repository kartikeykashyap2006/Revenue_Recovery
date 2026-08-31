# Architecture — AI Revenue Recovery Agent

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
signal -> diagnose (root cause) -> decide (playbook + guardrails) -> act (playbook) -> log (audit trail)
```

- **`app/models.py`** — the shared vocabulary: `Signal`, `Diagnosis`,
  `Decision`, `ActionResult`, `Trace`.
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
- **`app/engine/actions.py` + `app/playbooks/*.py`** — one module per
  scenario (`payment_retry`, `checkout_dropoff`, `subscription_mandate`,
  `receivables_chaser`), each producing a customer-facing recovery action
  (payment link + message) and a measured outcome.
- **`app/db.py`** — file-backed audit trail (append-only `audit_log.jsonl`).
  Every diagnosis, decision, and action is logged with its reasoning, plus
  contact history (for the stopping rules) and a promise-to-pay tracker for
  the B2B receivables flow, stored in `state.json`.
- **`app/reporting/batch_report.py`** — turns a batch of traces into the
  headline number the buildathon bar asks for: measured money recovered,
  broken down by scenario type and root cause, plus escalation/stop counts.

## Mapping to the buildathon's example directions

| Example direction | Where it lives |
|---|---|
| Payment degradation → root cause → recovery action | Core engine + `payment_retry` playbook |
| Checkout drop-off recovery | `checkout_dropoff` playbook |
| Failed-subscription recovery | `subscription_mandate` playbook (staged retry sequencing) |
| B2B receivables chaser | `receivables_chaser` playbook |
| Mandate retry sequencer | Built into `subscription_mandate` (attempt-aware retry probability + `MAX_CONTACT_ATTEMPTS`) |
| Promise-to-pay tracker | `db.record_promise_to_pay` inside `receivables_chaser` |
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

Every stage (`diagnosis`, `decision`, `action`, `message_sent:<channel>`)
is written to `audit_log` in SQLite with the full payload and reasoning, so
any recovery decision can be traced back to why it happened.

## From simulated to real Razorpay test-mode

`app/integrations/razorpay_client.py` falls back to a mocked payment link
when no API keys are configured, so the whole pipeline is demoable offline.
Once `RAZORPAY_KEY_ID`/`RAZORPAY_KEY_SECRET` are set, the same code path
creates real Razorpay test-mode payment links (`scripts/seed_test_data.py`),
and `app/main.py` exposes a `/webhook/razorpay` endpoint (HMAC-verified)
to receive real payment-link status updates and feed them back into the
audit trail.

## What's simulated vs. real

Recovery *outcomes* (whether a customer actually pays after being
contacted) are simulated with root-cause-aware probabilities for the batch
demo, since we can't force real customers to respond within a hackathon
timeline. The *mechanism* — diagnosis, policy, payment link creation,
messaging, audit logging — is real and runs the same way whether wired to
mocked or live Razorpay test-mode data. This tradeoff is called out
explicitly in the pitch.
