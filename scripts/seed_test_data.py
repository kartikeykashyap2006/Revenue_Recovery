#!/usr/bin/env python3
"""Creates a handful of real Razorpay test-mode payment links so the live
demo has real (test-mode) artifacts to point at in the Razorpay dashboard,
not just simulated ones. Requires RAZORPAY_KEY_ID/SECRET *and*
USE_LIVE_RAZORPAY=true in .env -- keys alone are not enough (see
app/integrations/razorpay_client.py for why), so this refuses to run
rather than silently producing fake links if the flag is off.

Usage:
    python scripts/seed_test_data.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings
from app.data.synthetic_generator import generate_batch
from app.integrations.razorpay_client import create_recovery_payment_link


def main():
    if not (settings.RAZORPAY_KEY_ID and settings.RAZORPAY_KEY_SECRET):
        print("RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET not set in .env -- add your test keys first.")
        return
    if not settings.USE_LIVE_RAZORPAY:
        print(
            "USE_LIVE_RAZORPAY is not 'true' in .env -- refusing to run, since this "
            "script's whole point is creating REAL test-mode links, and it would "
            "otherwise silently print fake rzp.io/mock/... links instead. "
            "Set USE_LIVE_RAZORPAY=true in .env and re-run."
        )
        return

    signals = generate_batch(n=5, seed=1)
    for s in signals:
        link = create_recovery_payment_link(s)
        print(f"{s.type.value:30s} {s.customer_name:20s} Rs.{s.amount:>10,.2f}  {link['short_url']}")


if __name__ == "__main__":
    main()
