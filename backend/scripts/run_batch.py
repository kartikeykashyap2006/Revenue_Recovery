#!/usr/bin/env python3
"""End-to-end demo entry point.

Usage:
    python scripts/run_batch.py --n 60 --seed 42
"""
import argparse
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.data.synthetic_generator import generate_batch
from app.engine.pipeline import process_batch
from app.reporting.batch_report import generate_report, print_report, save_report
from app.db import reset as reset_db, log_event
from app.config import settings


def _print_nvidia_diagnostics():
    """When the AI agent ran against the NVIDIA free tier, a batch's wall-clock
    time is almost entirely those network calls, and how slow they were is set
    by shared-worker congestion (503 'worker full'), not by anything local. Show
    the 503 rate and the interval the adaptive throttle settled on so a slow run
    can be attributed to a busy window rather than guessed at."""
    from app.integrations import llm

    stats = llm.nvidia_throttle_stats()
    attempts = stats["successes"] + stats["failures"] + stats["retries"]
    if attempts == 0:
        return
    interval = llm.current_nvidia_request_interval()
    floor = 60.0 / max(settings.NVIDIA_MAX_RPM, 1)
    backpressure = stats["http_503"] + stats["http_429"]
    print("\nNVIDIA throttle diagnostics (agent calls):")
    print(
        f"  outcomes: {stats['successes']} ok, "
        f"{stats['failures']} fell back to deterministic default, "
        f"{stats['retries']} retries"
    )
    print(
        f"  backpressure: {stats['http_503']}x 503 (shared worker full), "
        f"{stats['http_429']}x 429 "
        f"-- {100 * backpressure / attempts:.0f}% of {attempts} attempts"
    )
    print(
        f"  request interval: settled at {interval:.2f}s "
        f"(floor {floor:.2f}s @ {settings.NVIDIA_MAX_RPM} RPM, ceiling 6.00s) "
        f"-- higher = busier window = slower batch"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=60, help="Batch size")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility")
    parser.add_argument("--save-traces", action="store_true", help="Also dump per-signal traces to reports/traces.json")
    parser.add_argument("--reset", action="store_true", help="Clear the audit trail / contact history before running (fresh demo state)")
    parser.add_argument(
        "--simulate-time", type=str, default=None,
        help=(
            "ISO datetime (UTC) to evaluate quiet-hours against instead of the real "
            "current time, e.g. 2026-08-31T10:00:00 (=15:30 IST, well outside quiet "
            "hours). Useful for demos/testing so a real-world quiet-hours window "
            "doesn't block the whole batch. Compliance logic itself is unchanged -- "
            "this only controls what 'now' means for that one check."
        ),
    )
    args = parser.parse_args()

    simulated_now = datetime.fromisoformat(args.simulate_time) if args.simulate_time else None
    if simulated_now:
        print(f"Simulating now_utc={simulated_now.isoformat()} for quiet-hours evaluation.\n")

    if args.reset:
        reset_db()
        print("Reset audit trail and contact history for a fresh run.\n")

    signals = generate_batch(n=args.n, seed=args.seed, now_utc=simulated_now)
    print(
        f"Detected {len(signals)} at-risk signal(s) from {args.n} raw event-case(s) "
        f"({args.n - len(signals)} resolved on their own -- no signal needed).\n"
    )
    # Logged to the audit trail (not just printed) so scripts/system_metrics.py
    # can report the detection funnel across runs, not only the most recent one.
    log_event("__batch__", "batch_detection", {
        "raw_cases": args.n, "signals_detected": len(signals),
        "resolved_on_their_own": args.n - len(signals),
    })
    nvidia_agent_run = settings.LLM_PROVIDER == "nvidia" and settings.USE_AI_RECOVERY_AGENT
    if nvidia_agent_run:
        from app.integrations import llm
        llm.reset_nvidia_throttle_stats()

    traces = process_batch(signals, now_utc=simulated_now)
    report = generate_report(traces)

    print_report(report)
    if nvidia_agent_run:
        _print_nvidia_diagnostics()
    save_report(report)

    if args.save_traces:
        os.makedirs("reports", exist_ok=True)
        dump = [
            {
                "signal": {**t.signal.__dict__, "type": t.signal.type.value},
                "diagnosis": {**t.diagnosis.__dict__, "root_cause": t.diagnosis.root_cause.value},
                "decision": t.decision.__dict__,
                "action": {**t.action.__dict__, "channel": t.action.channel.value, "status": t.action.status.value},
            }
            for t in traces
        ]
        with open("reports/traces.json", "w") as f:
            json.dump(dump, f, indent=2, default=str)
        print("\nFull traces written to reports/traces.json")

    print("\nAudit trail stored in audit_log.jsonl -- every diagnosis/decision/action is logged there.")


if __name__ == "__main__":
    main()
