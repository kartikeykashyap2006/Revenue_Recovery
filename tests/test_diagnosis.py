from app.engine.diagnosis import diagnose
from app.models import Signal, SignalType, RootCause


def _signal(stype, reason_code, **meta):
    return Signal(
        type=stype, customer_id="c1", customer_name="Test User", amount=1000,
        metadata={"reason_code": reason_code, **meta},
    )


def test_known_payment_failure_reason_maps_correctly():
    sig = _signal(SignalType.PAYMENT_FAILURE, "card_expired")
    d = diagnose(sig)
    assert d.root_cause == RootCause.CARD_EXPIRED
    assert d.confidence > 0.9


def test_known_receivable_reason_maps_to_dispute():
    sig = _signal(SignalType.OVERDUE_RECEIVABLE, "disputed")
    d = diagnose(sig)
    assert d.root_cause == RootCause.INVOICE_DISPUTE


def test_unknown_reason_code_yields_unknown_with_zero_confidence():
    sig = _signal(SignalType.PAYMENT_FAILURE, "some_new_gateway_error_code")
    d = diagnose(sig)
    assert d.root_cause == RootCause.UNKNOWN
    assert d.confidence == 0.0
