#!/usr/bin/env python3
"""Creates a handful of real Razorpay test-mode payment links so the live
demo has real (test-mode) artifacts to point at in the Razorpay dashboard,
not just simulated ones. Requires RAZORPAY_KEY_ID/SECRET in .env.

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

    signals = generate_batch(n=5, seed=1)
    for s in signals:
        link = create_recovery_payment_link(s)
        print(f"{s.type.value:30s} {s.customer_name:20s} Rs.{s.amount:>10,.2f}  {link['short_url']}")


if __name__ == "__main__":
    main()
