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
