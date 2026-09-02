from app.models import Signal, SignalType, RootCause, Diagnosis

# Deterministic rule tables mapping raw failure/reason codes to root causes.
PAYMENT_FAILURE_RULES = {
    "insufficient_funds": (RootCause.INSUFFICIENT_FUNDS, 0.95),
    "card_expired": (RootCause.CARD_EXPIRED, 0.97),
    "risk_declined": (RootCause.BANK_DECLINED_RISK, 0.9),
    "gateway_timeout": (RootCause.NETWORK_ERROR, 0.85),
    "otp_mismatch": (RootCause.WRONG_OTP, 0.9),
    "limit_exceeded": (RootCause.EXCEEDED_LIMIT, 0.9),
}

CHECKOUT_ABANDONMENT_RULES = {
    "price_page_exit": (RootCause.PRICE_HESITATION, 0.7),
    "no_upi_available": (RootCause.PAYMENT_METHOD_UNAVAILABLE, 0.85),
    "checkout_error": (RootCause.TECHNICAL_GLITCH, 0.85),
    "session_timeout": (RootCause.DISTRACTED_TIMEOUT, 0.6),
}

MANDATE_FAILURE_RULES = {
    "insufficient_funds": (RootCause.INSUFFICIENT_FUNDS, 0.95),
    "mandate_expired": (RootCause.MANDATE_EXPIRED, 0.97),
    "card_expired": (RootCause.CARD_EXPIRED, 0.95),
    "bank_declined": (RootCause.BANK_DECLINED_RISK, 0.8),
}

RECEIVABLE_RULES = {
    "no_response": (RootCause.FORGOT, 0.6),
    "disputed": (RootCause.INVOICE_DISPUTE, 0.9),
    "cash_flow": (RootCause.CASH_FLOW_DELAY, 0.75),
}

RULES_BY_TYPE = {
    SignalType.PAYMENT_FAILURE: PAYMENT_FAILURE_RULES,
    SignalType.CHECKOUT_ABANDONMENT: CHECKOUT_ABANDONMENT_RULES,
    SignalType.SUBSCRIPTION_MANDATE_FAILURE: MANDATE_FAILURE_RULES,
    SignalType.OVERDUE_RECEIVABLE: RECEIVABLE_RULES,
}


def diagnose(signal: Signal) -> Diagnosis:
    """Rule-first diagnosis. Falls back to LLM diagnosis for low-confidence
    reason codes -- see engine.pipeline, which calls integrations.llm when
    USE_LLM_DIAGNOSIS is enabled."""
    rules = RULES_BY_TYPE.get(signal.type, {})
    reason_code = signal.metadata.get("reason_code", "")
    root_cause, confidence = rules.get(reason_code, (RootCause.UNKNOWN, 0.0))

    reasoning = (
        f"Matched reason_code='{reason_code}' for signal type '{signal.type.value}' "
        f"to root cause '{root_cause.value}' via rule table."
        if root_cause != RootCause.UNKNOWN
        else f"No rule match for reason_code='{reason_code}'; needs deeper diagnosis."
    )

    return Diagnosis(
        signal_id=signal.id,
        root_cause=root_cause,
        confidence=confidence,
        reasoning=reasoning,
    )
