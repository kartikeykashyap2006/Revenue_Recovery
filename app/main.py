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
    traces = process_batch(signals)
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
    return {"received": True}
