# 5-Minute Pitch Outline

## Demo command (use this exact one for a reproducible, representative run)

```bash
python scripts/run_batch.py --reset --n 80 --seed 7 --save-traces --simulate-time 2026-08-31T10:00:00
```

This seed/size combination reliably shows recovery, escalation, and a
stopped contact across all four scenario types in one run:

```
Batch size: 80
Total at risk: Rs. 23,87,220.71
Total recovered: Rs. 5,12,402.24
Recovery rate: 21.5%
Action outcomes: {'sent': 40, 'recovered': 28, 'stopped': 10, 'escalated': 2}
```

`--simulate-time` only controls what "now" means for the quiet-hours check
(so the demo isn't at the mercy of what time you happen to be recording) —
every other guardrail (opt-outs, escalation, max-contact, cooldown) runs on
real logic either way.

## 1. Problem (30s)

Revenue leaks through payment failures, checkout drop-off, failed
subscriptions, and overdue invoices — each looks different on the surface,
but shares the same shape: detect, diagnose, recover.

## 2. Live demo (2.5 min)

Run the command above on camera. Walk through one trace end-to-end using
`python scripts/inspect_audit.py --signal-id <id>` on a recovered payment
signal from `reports/traces.json`: a payment failure -> diagnosed as
`card_expired` -> `payment_retry` playbook -> payment link sent -> recovered.
Show the printed batch report (total at risk, total recovered, recovery
rate, breakdown by scenario type).

## 3. Compliance & guardrails (1 min)

Pull one `escalated` trace (an `invoice_dispute` or a high-value signal)
and one `stopped` trace (cooldown/quiet-hours/opt-out) from
`reports/traces.json`, and show their audit entries with
`python scripts/inspect_audit.py --signal-id <id>`. This is the "compliant
escalation, stopping rules, and an audit trail" the brief asks for, made
concrete on screen.

## 4. Architecture (45s)

One engine, pluggable playbooks (`app/playbooks/`), real Razorpay
test-mode integration via `payment_link.create` (falls back to mocked
links until keys are configured — same code path either way), optional
LLM-assisted diagnosis fallback for low-confidence signals, and 14 passing
tests covering diagnosis rules, policy guardrails, playbook mechanics, and
crash resilience (`pytest tests/ -v`).

## 5. What's next (15s)

Wire real webhook-driven outcomes instead of simulated recovery
probabilities (the `/webhook/razorpay` endpoint is already built and
signature-verified); add more playbooks without touching the core engine.
