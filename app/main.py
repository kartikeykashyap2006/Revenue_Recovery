"""FastAPI app: exposes the recovery engine over HTTP and receives Razorpay
webhooks so real payment-link outcomes can update the audit trail.

Run with: uvicorn app.main:app --reload
"""
import hashlib
import hmac
import json
from typing import Optional

from fastapi import FastAPI, Request, HTTPException

from app import db
from app.config import settings
from app.data.synthetic_generator import generate_batch
from app.engine.pipeline import process_batch
from app.engine.confirmation import confirm_from_webhook
from app.reporting.batch_report import generate_report, save_report

app = FastAPI(title="AI Revenue Recovery Agent")


@app.on_event("startup")
def startup():
    db.init_db()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/run-batch")
def run_batch(n: int = 60, seed: Optional[int] = None):
    signals = generate_batch(n=n, seed=seed)
    traces = process_batch(signals, show_progress=False)
    report = generate_report(traces)
    save_report(report)
    return report


@app.get("/audit-log")
def audit_log(signal_id: Optional[str] = None):
    return db.fetch_audit_log(signal_id)


def _verify_webhook_signature(body: bytes, signature: str) -> bool:
    if not settings.RAZORPAY_WEBHOOK_SECRET:
        return False
    expected = hmac.new(
        settings.RAZORPAY_WEBHOOK_SECRET.encode(), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


@app.post("/webhook/razorpay")
async def razorpay_webhook(request: Request):
    body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature", "")

    if settings.RAZORPAY_WEBHOOK_SECRET and not _verify_webhook_signature(body, signature):
        raise HTTPException(status_code=400, detail="invalid signature")

    payload = json.loads(body)
    event = payload.get("event", "unknown")
    db.log_event("webhook", f"razorpay_event:{event}", payload)

    # Close the loop: a real payment_link.paid/cancelled/expired event for
    # a link this system created should actually update the recovery it's
    # tracking, not just be logged and discarded. This is the other half
    # of app.engine.confirmation -- the simulated confirmation pass covers
    # the offline demo path, this covers a genuine live-mode webhook.
    link_id = (
        payload.get("payload", {})
        .get("payment_link", {})
        .get("entity", {})
        .get("id")
    )
    if link_id and event in ("payment_link.paid", "payment_link.cancelled", "payment_link.expired"):
        # Confirming a recovery MUTATES money-recovered state, so an
        # unsigned request must never be able to do it in live mode: with
        # no RAZORPAY_WEBHOOK_SECRET set, the signature check above is
        # skipped entirely, which would leave anyone who can reach this
        # endpoint able to mark arbitrary payment links as paid. Unsigned
        # requests stay allowed in mock mode only, so the endpoint is
        # still curl-testable locally during development.
        if not settings.RAZORPAY_WEBHOOK_SECRET and settings.USE_LIVE_RAZORPAY:
            return {
                "received": True,
                "recovery_update": "refused_unsigned_webhook_in_live_mode",
                "detail": "set RAZORPAY_WEBHOOK_SECRET to accept recovery confirmations",
            }

        paid = event == "payment_link.paid"
        record = confirm_from_webhook(link_id, paid=paid)
        if record is None:
            return {"received": True, "recovery_update": "no_matching_pending_recovery"}
        return {
            "received": True,
            "recovery_update": "confirmed" if paid else "not_recovered",
            "signal_id": record["signal_id"],
        }

    return {"received": True}
