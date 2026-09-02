"""File-backed audit trail and state store.

Deliberately NOT SQLite: this project directory can be a networked/mounted
folder (e.g. synced from a connected device folder), and SQLite's locking
model does not play well with non-local filesystems (surfaces as
'disk I/O error'). A plain append-only JSONL audit log plus a small JSON
state file is simpler, fully inspectable/diffable, and just as valid an
"audit trail" for the buildathon's requirements.
"""
import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

_AUDIT_LOG_PATH = "audit_log.jsonl"
_STATE_PATH = "state.json"

_DEFAULT_STATE: Dict[str, List[Any]] = {
    "contact_history": [],
    "opt_outs": [],
    "promises_to_pay": [],
    "pending_recoveries": [],
    "deferred_signals": [],
}


def _load_state() -> Dict[str, Any]:
    if not os.path.exists(_STATE_PATH):
        return {k: list(v) for k, v in _DEFAULT_STATE.items()}
    with open(_STATE_PATH, "r") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            data = {}
    for k, v in _DEFAULT_STATE.items():
        data.setdefault(k, list(v))
    return data


def _save_state(state: Dict[str, Any]) -> None:
    tmp_path = _STATE_PATH + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(state, f, indent=2, default=str)
    os.replace(tmp_path, _STATE_PATH)


def init_db() -> None:
    if not os.path.exists(_STATE_PATH):
        _save_state({k: list(v) for k, v in _DEFAULT_STATE.items()})
    if not os.path.exists(_AUDIT_LOG_PATH):
        open(_AUDIT_LOG_PATH, "a").close()


def log_event(signal_id: str, stage: str, payload: Dict[str, Any]) -> None:
    entry = {
        "signal_id": signal_id,
        "stage": stage,
        "payload": payload,
        "created_at": datetime.utcnow().isoformat(),
    }
    with open(_AUDIT_LOG_PATH, "a") as f:
        f.write(json.dumps(entry, default=str) + "\n")


def record_contact(customer_id: str, signal_id: str, channel: str) -> None:
    state = _load_state()
    state["contact_history"].append(
        {
            "customer_id": customer_id,
            "signal_id": signal_id,
            "channel": channel,
            "created_at": datetime.utcnow().isoformat(),
        }
    )
    _save_state(state)


def get_contact_count(customer_id: str) -> int:
    state = _load_state()
    return sum(1 for c in state["contact_history"] if c["customer_id"] == customer_id)


def get_last_contact_time(customer_id: str) -> Optional[datetime]:
    state = _load_state()
    times = [c["created_at"] for c in state["contact_history"] if c["customer_id"] == customer_id]
    if not times:
        return None
    return datetime.fromisoformat(max(times))


def is_opted_out(customer_id: str) -> bool:
    state = _load_state()
    return customer_id in state["opt_outs"]


def record_opt_out(customer_id: str) -> None:
    state = _load_state()
    if customer_id not in state["opt_outs"]:
        state["opt_outs"].append(customer_id)
    _save_state(state)


def record_promise_to_pay(signal_id: str, customer_id: str, amount: float, promised_date: str) -> None:
    state = _load_state()
    state["promises_to_pay"].append(
        {
            "signal_id": signal_id,
            "customer_id": customer_id,
            "promised_amount": amount,
            "promised_date": promised_date,
            "fulfilled": False,
            "created_at": datetime.utcnow().isoformat(),
        }
    )
    _save_state(state)


def record_pending_recovery(
    signal_id: str, playbook: str, amount: float, reference: str, recovery_probability: float
) -> None:
    """Registers that a playbook sent a customer-facing recovery action
    (a payment link, an invoice reminder) whose actual outcome is not yet
    known. `reference` is whatever a later confirmation event will be
    keyed on (a Razorpay payment_link id, or an invoice_id for
    receivables). `recovery_probability` is the playbook's own
    root-cause-aware estimate, carried over so the confirmation step can
    use it -- but critically, drawing against it now happens in a
    separate, distinctly-logged confirmation step (see
    app/engine/confirmation.py), not inline inside the playbook, so
    'recovered' is always the output of an explicit confirmation event
    rather than the playbook silently deciding its own outcome."""
    state = _load_state()
    state["pending_recoveries"].append(
        {
            "signal_id": signal_id,
            "playbook": playbook,
            "amount": amount,
            "reference": reference,
            "recovery_probability": recovery_probability,
            "confirmed": None,  # None = awaiting confirmation; True/False once resolved
            "confirmed_via": None,
            "created_at": datetime.utcnow().isoformat(),
        }
    )
    _save_state(state)


def list_unconfirmed_recoveries() -> List[Dict[str, Any]]:
    state = _load_state()
    return [r for r in state["pending_recoveries"] if r["confirmed"] is None]


def find_pending_recovery_by_reference(reference: str) -> Optional[Dict[str, Any]]:
    """Looks up a still-unconfirmed pending recovery by its reference (a
    payment_link id) -- this is how a real Razorpay webhook (see
    app.engine.confirmation.confirm_from_webhook) figures out which signal
    a `payment_link.paid` event belongs to."""
    state = _load_state()
    for r in state["pending_recoveries"]:
        if r["reference"] == reference and r["confirmed"] is None:
            return r
    return None


def confirm_recovery(signal_id: str, confirmed: bool, source: str) -> Optional[Dict[str, Any]]:
    """Resolves the first still-unconfirmed pending recovery for this
    signal. `source` records what confirmed it -- e.g.
    'simulated_gateway_confirmation' for the offline demo path, or
    'razorpay_webhook' for a real confirmation -- so the audit trail can
    always show whether a given RECOVERED outcome came from a real
    external event or a simulated stand-in for one."""
    state = _load_state()
    for r in state["pending_recoveries"]:
        if r["signal_id"] == signal_id and r["confirmed"] is None:
            r["confirmed"] = confirmed
            r["confirmed_via"] = source
            r["confirmed_at"] = datetime.utcnow().isoformat()
            _save_state(state)
            return r
    return None


def fetch_audit_log(signal_id: Optional[str] = None) -> List[Dict[str, Any]]:
    if not os.path.exists(_AUDIT_LOG_PATH):
        return []
    entries: List[Dict[str, Any]] = []
    with open(_AUDIT_LOG_PATH, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            if signal_id is None or entry["signal_id"] == signal_id:
                entries.append(entry)
    return entries


def record_deferred_signal(signal_dict: Dict[str, Any], not_before: str, reason: str) -> None:
    """Persists a signal the AI agent judged premature to contact right now,
    so a LATER batch can pick it up once `not_before` has passed.

    The whole signal is stored, not just its id, because synthetic batches
    are regenerated per run -- without this the deferral would be recorded
    and then quietly never acted on, which is exactly the kind of claim
    this system is not allowed to make. See
    app.engine.pipeline.process_batch, which loads due deferrals and puts
    them through the FULL pipeline again (every guardrail re-evaluated
    against the later clock), so deferring can only ever postpone contact.
    """
    state = _load_state()
    state["deferred_signals"].append(
        {
            "signal": signal_dict,
            "not_before": not_before,
            "reason": reason,
            "released": False,
            "created_at": datetime.utcnow().isoformat(),
        }
    )
    _save_state(state)


def list_due_deferred_signals(now_utc: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Deferrals whose wait has elapsed as of `now_utc`, still unreleased."""
    now_utc = now_utc or datetime.utcnow()
    state = _load_state()
    due = []
    for record in state["deferred_signals"]:
        if record.get("released"):
            continue
        if datetime.fromisoformat(record["not_before"]) <= now_utc:
            due.append(record)
    return due


def release_deferred_signal(signal_id: str) -> bool:
    """Marks a deferral as released so it is picked up exactly once."""
    state = _load_state()
    for record in state["deferred_signals"]:
        if not record.get("released") and record["signal"].get("id") == signal_id:
            record["released"] = True
            record["released_at"] = datetime.utcnow().isoformat()
            _save_state(state)
            return True
    return False
