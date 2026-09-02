#!/usr/bin/env python3
"""Live-mode reconciliation: asks Razorpay what actually happened to every
still-unconfirmed recovery payment link this system created, and resolves
them the same way a webhook would.

Why this exists: the webhook path (app/main.py's /webhook/razorpay) needs
a publicly reachable URL, which a laptop running a demo generally isn't.
Without this, a genuinely paid test-mode link would never make it back
into the system. Same pending-recovery records, same db.confirm_recovery()
call, same "confirmation" audit stage as the webhook path -- only the
logged `source` differs (razorpay_link_poll vs razorpay_webhook).

Requires USE_LIVE_RAZORPAY=true plus test-mode keys; mock links
(plink_mock_...) are skipped since they have no upstream status.

Usage:
    python scripts/reconcile_recoveries.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings
from app.engine.confirmation import reconcile_pending_recoveries


def main():
    if not settings.USE_LIVE_RAZORPAY:
        print(
            "USE_LIVE_RAZORPAY is not 'true' -- nothing to reconcile, since every "
            "payment link in mock mode is a local plink_mock_... id with no "
            "upstream status to poll. Set USE_LIVE_RAZORPAY=true with test-mode "
            "keys and re-run after creating real links."
        )
        return

    result = reconcile_pending_recoveries()
    print(
        f"Polled {result['checked']} live payment link(s): "
        f"{result['resolved']} resolved, {result['recovered']} confirmed as recovered."
    )
    if result["checked"] == 0:
        print("(No unconfirmed recoveries with real payment-link references were pending.)")


if __name__ == "__main__":
    main()
