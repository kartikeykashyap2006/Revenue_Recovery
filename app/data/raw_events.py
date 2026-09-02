"""Generates a raw, unlabeled stream of Razorpay-style events -- the kind
of thing a real system would actually receive (payment webhooks, checkout
session telemetry, subscription charge attempts, invoice lifecycle
events) -- with NO signal category attached. app.engine.detection is what
turns this into Signal objects, by correlating events per case and
checking whether the case ever resolved on its own.

This is deliberately separate from "diagnosis" (app/engine/diagnosis.py,
unchanged): detection answers "is there a revenue-at-risk situation here
at all, and which of the four categories is it", using event correlation
and timing. Diagnosis still separately answers "why", from the resulting
signal's reason_code -- that stage was already real and isn't touched.
"""
import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from app.models import SignalType

FIRST_NAMES = [
    "Aarav", "Vivaan", "Aditya", "Vihaan", "Arjun", "Sai", "Reyansh", "Krishna",
    "Ishaan", "Rohan", "Ananya", "Diya", "Priya", "Isha", "Kavya", "Meera",
    "Neha", "Pooja", "Riya", "Sneha",
]
LAST_NAMES = [
    "Sharma", "Verma", "Gupta", "Iyer", "Nair", "Reddy", "Rao", "Mehta",
    "Kapoor", "Joshi", "Patel", "Singh", "Kulkarni", "Bansal", "Chatterjee",
]

PAYMENT_FAILURE_CODES = ["insufficient_funds", "card_expired", "risk_declined", "gateway_timeout", "otp_mismatch", "limit_exceeded"]
CHECKOUT_CODES = ["price_page_exit", "no_upi_available", "checkout_error", "session_timeout"]
MANDATE_CODES = ["insufficient_funds", "mandate_expired", "card_expired", "bank_declined"]
RECEIVABLE_CODES = ["no_response", "disputed", "cash_flow"]

# Every code above has a matching entry in app/engine/diagnosis.py's rule
# tables, so without this, diagnosis confidence is never below 0.5 and
# USE_LLM_DIAGNOSIS's fallback path is never actually exercised by a
# normal batch. A small fraction of cases instead get a code no rule
# table recognizes -- standing in for a genuinely novel gateway/decline
# code a real payments system does eventually see.
UNRECOGNIZED_CODE_PROBABILITY = 0.05
UNRECOGNIZED_CODES = ["unclassified_gateway_response_412", "new_decline_code_unseen"]

# Probability that a given case resolves on its own before detection runs
# (customer retried and it went through, they came back and paid, the
# invoice got settled) -- these cases correctly produce NO signal. This is
# what makes detection real filtering instead of a relabeling exercise.
RESOLVE_PROBABILITY = 0.3

SCENARIO_WEIGHTS = {
    SignalType.PAYMENT_FAILURE: 0.35,
    SignalType.CHECKOUT_ABANDONMENT: 0.3,
    SignalType.SUBSCRIPTION_MANDATE_FAILURE: 0.2,
    SignalType.OVERDUE_RECEIVABLE: 0.15,
}


@dataclass
class RawEvent:
    """One raw event as a real webhook/telemetry stream would deliver it
    -- no signal category, just what happened, to what case, when."""
    event_type: str
    case_id: str
    customer_id: str
    customer_name: str
    amount: float
    currency: str
    timestamp: datetime
    payload: Dict[str, Any] = field(default_factory=dict)


def _name() -> str:
    return f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"


def _lang() -> str:
    return random.choices(["en", "hi"], weights=[0.45, 0.55])[0]


def _customer_id(name: str, idx: int) -> str:
    return f"cust_{name.split()[0].lower()}_{idx}"


def _phone() -> str:
    return f"{random.choice('6789')}{''.join(random.choices('0123456789', k=9))}"


def _email(name: str) -> str:
    first = name.split()[0].lower()
    return f"{first}.test.{random.randint(100, 999)}@example.com"


def _code(pool: List[str]) -> str:
    if random.random() < UNRECOGNIZED_CODE_PROBABILITY:
        return random.choice(UNRECOGNIZED_CODES)
    return random.choice(pool)


def _case_events(stype: SignalType, idx: int, now_utc: datetime) -> List[RawEvent]:
    case_id = f"{stype.value}_{idx}_{uuid.uuid4().hex[:6]}"
    name = _name()
    cust_id = _customer_id(name, idx)
    lang = _lang()
    phone, email = _phone(), _email(name)
    resolved = random.random() < RESOLVE_PROBABILITY
    events: List[RawEvent] = []

    def emit(event_type: str, ts: datetime, amount: float, **payload) -> None:
        events.append(RawEvent(
            event_type=event_type, case_id=case_id, customer_id=cust_id,
            customer_name=name, amount=amount, currency="INR", timestamp=ts,
            payload={"language_pref": lang, "phone": phone, "email": email, **payload},
        ))

    if stype == SignalType.PAYMENT_FAILURE:
        amount = round(random.uniform(299, 15000), 2)
        t0 = now_utc - timedelta(hours=random.uniform(1, 48))
        emit("payment.failed", t0, amount,
             error_code=_code(PAYMENT_FAILURE_CODES),
             payment_method=random.choice(["card", "upi", "netbanking"]))
        if resolved:
            emit("payment.captured", t0 + timedelta(minutes=random.uniform(2, 40)), amount)

    elif stype == SignalType.CHECKOUT_ABANDONMENT:
        amount = round(random.uniform(499, 25000), 2)
        t0 = now_utc - timedelta(hours=random.uniform(1, 48))
        emit("checkout.session.started", t0, amount, friction_hint=_code(CHECKOUT_CODES))
        if resolved:
            emit("payment.captured", t0 + timedelta(minutes=random.uniform(5, 90)), amount)

    elif stype == SignalType.SUBSCRIPTION_MANDATE_FAILURE:
        amount = round(random.uniform(199, 2999), 2)
        attempts = random.randint(1, 3)
        t0 = now_utc - timedelta(days=attempts + random.uniform(0, 1))
        last_code = None
        for attempt in range(1, attempts + 1):
            last_code = _code(MANDATE_CODES)
            emit("subscription.charge.failed", t0 + timedelta(days=attempt - 1), amount,
                 error_code=last_code, attempt=attempt)
        if resolved:
            emit("subscription.charge.succeeded", t0 + timedelta(days=attempts), amount)

    else:  # OVERDUE_RECEIVABLE
        amount = round(random.uniform(15000, 400000), 2)
        days_overdue = random.randint(3, 45)
        due_date = now_utc - timedelta(days=days_overdue)
        created_at = due_date - timedelta(days=random.randint(30, 60))
        emit("invoice.created", created_at, amount,
             invoice_id=f"inv_{case_id}", due_date=due_date.date().isoformat(),
             status_hint=_code(RECEIVABLE_CODES))
        if resolved:
            emit("invoice.paid", due_date + timedelta(days=random.uniform(0, 2)), amount)

    return events


def generate_raw_event_stream(
    n_cases: int, seed: Optional[int] = None, now_utc: Optional[datetime] = None
) -> List[RawEvent]:
    """Simulates n_cases independent customer/transaction cases, each
    emitting its own real event sequence (some of which resolve on their
    own and correctly leave no trace worth acting on), then interleaves
    every event from every case by timestamp -- so the result reads like
    an actual raw event stream, not pre-grouped, pre-labeled fixtures."""
    if seed is not None:
        random.seed(seed)
    now_utc = now_utc or datetime.utcnow()

    types = list(SCENARIO_WEIGHTS.keys())
    weights = list(SCENARIO_WEIGHTS.values())

    events: List[RawEvent] = []
    for i in range(n_cases):
        stype = random.choices(types, weights=weights)[0]
        events.extend(_case_events(stype, i, now_utc))

    events.sort(key=lambda e: e.timestamp)
    return events
