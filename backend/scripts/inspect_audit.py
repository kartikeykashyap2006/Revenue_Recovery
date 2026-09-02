#!/usr/bin/env python3
"""Pretty-prints the audit trail for a demo/pitch video -- either the full
recent history, or the complete trace for one signal_id.

Usage:
    python scripts/inspect_audit.py                  # last 20 events
    python scripts/inspect_audit.py --signal-id ab12cd34
    python scripts/inspect_audit.py --status escalated --n 5
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--signal-id", type=str, default=None, help="Show the full trace for one signal")
    parser.add_argument("--n", type=int, default=20, help="How many recent events to show (ignored with --signal-id)")
    args = parser.parse_args()

    entries = db.fetch_audit_log(args.signal_id)
    if not entries:
        print("No audit log entries found. Run scripts/run_batch.py first.")
        return

    to_show = entries if args.signal_id else entries[-args.n:]
    for e in to_show:
        print(f"[{e['created_at']}] signal={e['signal_id']:10s} stage={e['stage']}")
        print(f"    {json.dumps(e['payload'], indent=2, default=str)[:500]}")
        print()


if __name__ == "__main__":
    main()
