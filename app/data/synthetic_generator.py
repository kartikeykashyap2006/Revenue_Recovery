"""Generates realistic synthetic batches of at-risk-revenue signals across
all four scenario types, for offline demoing and testing without needing
live Razorpay traffic."""
import random
from datetime import datetime, timedelta
from typing import List, Optional

from app.models import Signal, SignalType

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


def _name() -> str:
    return f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"


def _lang() -> str:
    return random.choices(["en", "hi"], weights=[0.45, 0.55])[0]


def _customer_id(name: str, idx: int) -> str:
    return f"cust_{name.split()[0].lower()}_{idx}"


def generate_batch(n: int = 60, seed: Optional[int] = None) -> List[Signal]:
    if seed is not None:
        random.seed(seed)

    signals: List[Signal] = []
    for i in range(n):
        stype = random.choices(
            list(SignalType),
            weights=[0.35, 0.3, 0.2, 0.15],
        )[0]
        name = _name()
        cust_id = _customer_id(name, i)
        lang = _lang()

        if stype == SignalType.PAYMENT_FAILURE:
            amount = round(random.uniform(299, 15000), 2)
            code = random.choice(PAYMENT_FAILURE_CODES)
            meta = {"reason_code": code, "payment_method": random.choice(["card", "upi", "netbanking"])}
        elif stype == SignalType.CHECKOUT_ABANDONMENT:
            amount = round(random.uniform(499, 25000), 2)
            code = random.choice(CHECKOUT_CODES)
            meta = {"reason_code": code, "checkout_id": f"chk_{i}"}
        elif stype == SignalType.SUBSCRIPTION_MANDATE_FAILURE:
            amount = round(random.uniform(199, 2999), 2)
            code = random.choice(MANDATE_CODES)
            meta = {"reason_code": code, "attempt_count": random.randint(1, 3)}
        else:  # OVERDUE_RECEIVABLE
            amount = round(random.uniform(15000, 400000), 2)
            code = random.choice(RECEIVABLE_CODES)
            due_date = (datetime.utcnow() - timedelta(days=random.randint(3, 45))).date().isoformat()
            meta = {"reason_code": code, "due_date": due_date, "invoice_id": f"inv_{i}"}

        signals.append(
            Signal(
                type=stype,
                customer_id=cust_id,
                customer_name=name,
                amount=amount,
                language_pref=lang,
                metadata=meta,
            )
        )
    return signals
