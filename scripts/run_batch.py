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
from app.db import _DEFAULT_STATE, _save_state, _AUDIT_LOG_PATH


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
        _save_state({k: list(v) for k, v in _DEFAULT_STATE.items()})
        open(_AUDIT_LOG_PATH, "w").close()
        print("Reset audit trail and contact history for a fresh run.\n")

    signals = generate_batch(n=args.n, seed=args.seed)
    traces = process_batch(signals, now_utc=simulated_now)
    report = generate_report(traces)

    print_report(report)
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
