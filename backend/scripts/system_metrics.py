#!/usr/bin/env python3
"""Aggregate performance metrics computed from the audit trail -- how the
system is actually behaving, not just the last batch's headline numbers.

There's no labeled ground truth to score diagnosis/detection "accuracy"
against (the rule tables ARE the ground truth, applied deterministically)
-- what's meaningful instead is: how often the AI agent actually changes
the deterministic outcome vs just agrees with it, its confidence and
error/fallback rate, the diagnosis confidence spread, why things get
escalated or stopped, and the detection funnel (raw event-cases -> real
signals -> resolved-on-their-own).

Usage:
    python scripts/system_metrics.py
"""
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db



def _channel_summary(real_answers) -> str:
    """How often the agent picked the outreach channel itself, rather than
    accepting the playbook's default."""
    chosen = Counter(r["channel"] for r in real_answers if r.get("channel"))
    if not chosen:
        return "0 -- every send used its playbook's default channel"
    total = sum(chosen.values())
    breakdown = ", ".join(f"{k}={v}" for k, v in chosen.most_common())
    return f"{total} ({total/len(real_answers):.0%}): {breakdown}"


def _defer_summary(real_answers) -> str:
    """How often the agent judged now to be the wrong moment and scheduled
    the outreach for later instead (app/engine/actions.py persists these;
    a later batch re-evaluates them against every guardrail again)."""
    deferrals = [int(r.get("defer_hours") or 0) for r in real_answers]
    postponed = [d for d in deferrals if d > 0]
    if not postponed:
        return "0 -- no outreach was postponed"
    return (
        f"{len(postponed)} ({len(postponed)/len(real_answers):.0%}), "
        f"average delay {sum(postponed)/len(postponed):.1f}h"
    )


def main():
    entries = db.fetch_audit_log()
    if not entries:
        print("No audit log entries found. Run scripts/run_batch.py first.")
        return

    by_stage = {}
    for e in entries:
        by_stage.setdefault(e["stage"], []).append(e["payload"])

    detections = by_stage.get("batch_detection", [])
    diagnoses = by_stage.get("diagnosis", [])
    decisions = by_stage.get("decision", [])
    ai_recs = by_stage.get("ai_recommendation", [])
    refinements = by_stage.get("decision_ai_refined", [])
    actions = by_stage.get("action", [])
    confirmations = by_stage.get("confirmation", [])

    lines = []

    if detections:
        total_cases = sum(d["raw_cases"] for d in detections)
        total_signals = sum(d["signals_detected"] for d in detections)
        total_resolved = sum(d["resolved_on_their_own"] for d in detections)
        lines.append(("Detection funnel (across all logged runs)", [
            (f"Raw event-cases considered", str(total_cases)),
            (f"Resolved on their own (no signal needed)", f"{total_resolved} ({total_resolved/total_cases:.0%})" if total_cases else "0"),
            (f"Real signals detected", f"{total_signals} ({total_signals/total_cases:.0%})" if total_cases else "0"),
        ]))

    if diagnoses:
        confidences = [d["confidence"] for d in diagnoses]
        low_conf = sum(1 for c in confidences if c < 0.5)
        by_cause = Counter(d["root_cause"] for d in diagnoses)
        lines.append(("Diagnosis", [
            ("Total diagnoses", str(len(diagnoses))),
            ("Average confidence", f"{sum(confidences)/len(confidences):.2f}"),
            ("Low-confidence (<0.5, needs LLM fallback if enabled)", f"{low_conf} ({low_conf/len(diagnoses):.0%})"),
            ("Top root causes", ", ".join(f"{k}={v}" for k, v in by_cause.most_common(5))),
        ]))

    if decisions:
        n = len(decisions)
        n_escalate = sum(1 for d in decisions if d["escalate"])
        n_stop = sum(1 for d in decisions if d["stop"])
        stop_reasons = Counter(d["stop_reason"] for d in decisions if d["stop_reason"])
        lines.append(("Policy / guardrails", [
            ("Total decisions", str(n)),
            ("Escalated by a guardrail", f"{n_escalate} ({n_escalate/n:.0%})"),
            ("Stopped by a guardrail", f"{n_stop} ({n_stop/n:.0%})"),
            ("Stop/escalate reasons", ", ".join(f"{k}={v}" for k, v in stop_reasons.most_common()) or "none triggered"),
        ]))

    if ai_recs:
        n = len(ai_recs)
        errors = [r for r in ai_recs if r.get("error")]
        real = [r for r in ai_recs if not r.get("error")]
        action_counts = Counter(r["action"] for r in real)
        lines.append(("AI recovery-decision agent", [
            ("Total consultations", str(n)),
            ("Real model answers", f"{len(real)} ({len(real)/n:.0%})"),
            ("Fell back (bad key / network / parse failure)", f"{len(errors)} ({len(errors)/n:.0%})"),
            ("Action distribution (real answers only)", ", ".join(f"{k}={v}" for k, v in action_counts.most_common()) or "n/a"),
            ("Average confidence (real answers only)", f"{sum(r['confidence'] for r in real)/len(real):.2f}" if real else "n/a"),
            ("Actually changed the deterministic outcome", f"{len(refinements)} ({len(refinements)/n:.0%} of consultations)"),
            ("Chose a non-default channel", _channel_summary(real)),
            ("Postponed outreach", _defer_summary(real)),
        ]))
    else:
        lines.append(("AI recovery-decision agent", [
            ("Total consultations", "0 -- USE_AI_RECOVERY_AGENT is off, or no batch has run with it on"),
        ]))

    if actions:
        status_counts = Counter(a["status"] for a in actions)
        lines.append(("Action outcomes", [
            (k, str(v)) for k, v in status_counts.most_common()
        ]))

    if confirmations:
        confirmed = [c for c in confirmations if c["confirmed"]]
        total_amount = sum(c["amount"] for c in confirmed)
        lines.append(("Recovery confirmation", [
            ("Total confirmation events", str(len(confirmations))),
            ("Confirmed recovered", f"{len(confirmed)} ({len(confirmed)/len(confirmations):.0%})"),
            ("Total confirmed amount (Rs.)", f"{total_amount:,.2f}"),
        ]))

    try:
        from rich.console import Console
        from rich.table import Table

        console = Console()
        for title, rows in lines:
            table = Table(title=title, show_header=False)
            table.add_column("metric")
            table.add_column("value")
            for k, v in rows:
                table.add_row(k, v)
            console.print(table)
    except ImportError:
        for title, rows in lines:
            print(f"\n== {title} ==")
            for k, v in rows:
                print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
