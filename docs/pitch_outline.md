# 5-Minute Pitch Outline

1. **Problem (30s)** — Revenue leaks through payment failures, checkout
   drop-off, failed subscriptions, and overdue invoices — each looks
   different but shares the same shape: detect, diagnose, recover.
2. **Live demo (2.5 min)** — Run `python scripts/run_batch.py --reset --n 80 --seed 7 --save-traces`
   (this seed reliably shows recovery, escalation, and a stopped contact
   across all four scenario types in one run)
   on camera. Walk through one trace end-to-end: a payment failure ->
   diagnosed as `card_expired` -> `payment_retry` playbook -> payment link
   sent -> recovered. Show the printed batch report (total at risk, total
   recovered, recovery rate, breakdown by scenario type).
3. **Compliance & guardrails (1 min)** — Show one signal that gets
   escalated instead of auto-contacted (e.g. `invoice_dispute`), and one
   that gets stopped by the cooldown/quiet-hours rule. Show a few lines from
   `audit_log.jsonl` so judges see the reasoning trail.
4. **Architecture (45s)** — One engine, pluggable playbooks, real Razorpay
   test-mode integration via `payment_link.create`, optional LLM-assisted
   diagnosis fallback.
5. **What's next (15s)** — Wire real webhook-driven outcomes instead of
   simulated recovery probabilities; add more playbooks without touching
   the core engine.
