"""FastAPI app: exposes the recovery engine over HTTP and receives Razorpay
webhooks so real payment-link outcomes can update the audit trail.

Run with: uvicorn app.main:app --reload
"""
import hashlib
import hmac
import json
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app import db
from app.config import settings
from app.data.synthetic_generator import generate_batch
from app.engine.pipeline import process_batch
from app.engine.confirmation import confirm_from_webhook
from app.reporting.batch_report import generate_report, save_report
from app.reporting.dashboard_data import build_payload

app = FastAPI(title="AI Revenue Recovery Agent")

# The TypeScript frontend runs on its own dev server (Vite, :5173) and calls
# this API cross-origin. Origins are listed explicitly rather than "*": this
# API can trigger batches and returns customer contact details, so a wildcard
# would let any page a developer happens to have open drive it.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173", "http://127.0.0.1:5173",   # vite dev server
        "http://localhost:4173", "http://127.0.0.1:4173",   # vite preview
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    db.init_db()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/run-batch")
def run_batch(n: int = 60, seed: Optional[int] = None):
    signals = generate_batch(n=n, seed=seed)
    db.log_event("__batch__", "batch_detection", {
        "raw_cases": n, "signals_detected": len(signals),
        "resolved_on_their_own": n - len(signals),
    })
    traces = process_batch(signals, show_progress=False)
    report = generate_report(traces)
    save_report(report)
    return report


@app.get("/api/config")
def config():
    """Read-only knobs the frontend needs to render run controls honestly --
    e.g. whether the AI agent is even consultable this run, so the UI never
    has to *infer* that from a batch that happened to consult it zero times
    (which also happens when the flag is on but no signal cleared every
    guardrail)."""
    return {
        "use_ai_recovery_agent": settings.USE_AI_RECOVERY_AGENT,
        "llm_provider": settings.LLM_PROVIDER,
    }


@app.get("/api/dashboard")
def dashboard():
    """Everything the frontend renders, computed once in
    app/reporting/dashboard_data.py -- the same function the offline HTML
    dashboard uses, so the two surfaces can never disagree about a run."""
    return build_payload()


@app.post("/api/run-batch")
def api_run_batch(n: int = 25, seed: Optional[int] = None, simulate_time: Optional[str] = None):
    """Runs a batch and returns the fresh dashboard payload.

    Synchronous on purpose: at demo sizes a batch is seconds, and a job queue
    would be machinery with nothing to do. It is also why n is small by
    default -- with the AI agent on, every signal that clears the guardrails
    makes a real model call.
    """
    if simulate_time:
        try:
            now_utc = datetime.fromisoformat(simulate_time)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"simulate_time is not a valid ISO datetime: {simulate_time!r}")
    else:
        now_utc = None
    signals = generate_batch(n=n, seed=seed, now_utc=now_utc)
    # Logged to the audit trail (mirroring scripts/run_batch.py) so
    # dashboard_data.py's _latest_batch can find *this* run's boundary --
    # without it, every API-triggered run silently folds into whatever the
    # last CLI run logged, and the funnel/recovery-rate numbers quietly
    # start describing "everything since the last CLI --reset" instead of
    # the batch that was just requested.
    db.log_event("__batch__", "batch_detection", {
        "raw_cases": n, "signals_detected": len(signals),
        "resolved_on_their_own": n - len(signals),
    })
    traces = process_batch(signals, now_utc=now_utc, show_progress=False)
    report = generate_report(traces)
    save_report(report)
    return build_payload()


@app.post("/api/reset")
def api_reset():
    """Clears the audit trail and all accumulated state, then returns the
    now-empty dashboard payload. The UI has no other way to start clean:
    every "Run batch" appends to the same store (contact history, pending
    recoveries) rather than replacing it, which is correct for showing the
    passage of time across runs but means a long demo session slowly piles
    up state. This is the button that gets back to a blank slate, the same
    reset scripts/run_batch.py --reset performs -- one shared db.reset()."""
    db.reset()
    return build_payload()


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
