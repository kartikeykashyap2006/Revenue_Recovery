"""One computation of "what happened in the latest batch", shared by every
surface that shows it.

Both the offline HTML dashboard (scripts/build_dashboard.py) and the JSON API
the TypeScript frontend calls (app/main.py) read from here, so the two can
never drift into disagreeing about the same run -- which is exactly what would
happen if each recomputed totals from the audit log its own way.

Everything is derived from audit_log.jsonl alone. Nothing is stored twice.
"""
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional

from app import db

STAGE_LABELS = {
    "signal": "signal detected",
    "diagnosis": "diagnosed",
    "decision": "policy decision",
    "ai_recommendation": "AI agent consulted",
    "decision_ai_refined": "AI changed the outcome",
    "action": "action",
    "confirmation": "confirmation",
    "promise_kept": "promise kept",
    "promise_broken": "promise broken",
}


def _latest_batch(entries: List[dict]):
    """Everything after the last batch_detection marker: one run, so repeated
    runs sharing an audit log are never double-counted."""
    starts = [i for i, e in enumerate(entries) if e["stage"] == "batch_detection"]
    if not starts:
        return entries, None, 0
    return entries[starts[-1]:], entries[starts[-1]]["payload"], len(starts)


def _collect_cases(events: List[dict]) -> Dict[str, dict]:
    cases: Dict[str, dict] = defaultdict(
        lambda: {"stages": [], "signal": None, "action": None, "ai": None,
                 "refined": False, "confirmation": None}
    )
    for e in events:
        sid = e["signal_id"]
        if sid in ("__batch__", "webhook"):
            continue
        c = cases[sid]
        c["stages"].append(e)
        if e["stage"] == "signal":
            c["signal"] = e["payload"]
        elif e["stage"] == "action":
            c["action"] = e["payload"]
        elif e["stage"] == "ai_recommendation":
            c["ai"] = e["payload"]
        elif e["stage"] == "decision_ai_refined":
            c["refined"] = True
        elif e["stage"] == "confirmation":
            c["confirmation"] = e["payload"]
    return {k: v for k, v in cases.items() if v["signal"] and v["action"]}


def build_payload(entries: Optional[List[dict]] = None) -> Dict[str, Any]:
    """The whole dashboard as plain JSON-serialisable data."""
    entries = entries if entries is not None else db.fetch_audit_log()
    if not entries:
        return {"empty": True, "reason": "no audit log entries -- run a batch first"}

    events, detection, run_count = _latest_batch(entries)
    cases = _collect_cases(events)
    if not cases:
        return {"empty": True, "reason": "no complete cases in the latest batch"}

    # An "action" event is written when the outreach is SENT, strictly before
    # the confirmation pass runs -- so in the log every action reads
    # status=sent, amount_recovered=0 forever. Recovery lives only in the
    # later "confirmation" stage, and reading the action event for money would
    # report zero recovered on a batch that recovered plenty.
    for c in cases.values():
        conf = c["confirmation"]
        if conf and conf.get("confirmed"):
            c["outcome"], c["recovered"] = "recovered", conf.get("amount", 0) or 0
        else:
            c["outcome"], c["recovered"] = c["action"]["status"], 0.0

    at_risk = sum(c["signal"]["amount"] for c in cases.values())
    recovered = sum(c["recovered"] for c in cases.values())
    outcomes = Counter(c["outcome"] for c in cases.values())

    by_type: Dict[str, dict] = defaultdict(lambda: {"at_risk": 0.0, "recovered": 0.0, "count": 0})
    for c in cases.values():
        t = by_type[c["signal"]["type"]]
        t["at_risk"] += c["signal"]["amount"]
        t["recovered"] += c["recovered"]
        t["count"] += 1

    raw = detection["raw_cases"] if detection else len(cases)
    detected = detection["signals_detected"] if detection else len(cases)
    contacted = outcomes.get("sent", 0) + outcomes.get("recovered", 0)

    ai = [c["ai"] for c in cases.values() if c["ai"]]
    ai_real = [a for a in ai if not a.get("error")]
    confidences = [a.get("confidence", 0) or 0 for a in ai_real]

    return {
        "empty": False,
        "runs_in_log": run_count,
        "totals": {
            "signals": len(cases),
            "at_risk": round(at_risk, 2),
            "recovered": round(recovered, 2),
            "recovery_rate": round(recovered / at_risk, 4) if at_risk else 0.0,
        },
        "detection": {
            "raw_cases": raw,
            "signals_detected": detected,
            "resolved_on_their_own": raw - detected,
        },
        "funnel": [
            {"label": "Raw event-cases", "value": raw,
             "note": "every case the stream contained"},
            {"label": "Needed a signal", "value": detected,
             "note": "the rest resolved without us"},
            {"label": "Contacted", "value": contacted,
             "note": "cleared every compliance guardrail"},
            {"label": "Confirmed recovered", "value": outcomes.get("recovered", 0),
             "note": "a real confirmation event said so"},
        ],
        "by_scenario": [
            {
                "type": t,
                "count": v["count"],
                "at_risk": round(v["at_risk"], 2),
                "recovered": round(v["recovered"], 2),
                "rate": round(v["recovered"] / v["at_risk"], 4) if v["at_risk"] else 0.0,
            }
            for t, v in sorted(by_type.items(), key=lambda kv: -kv[1]["at_risk"])
        ],
        "outcomes": dict(outcomes),
        "agent": {
            "consultations": len(ai),
            "real_answers": len(ai_real),
            "fallbacks": len(ai) - len(ai_real),
            "changed_outcome": sum(1 for c in cases.values() if c["refined"]),
            "chose_channel": sum(1 for a in ai_real if a.get("channel")),
            "postponed": sum(1 for a in ai_real if (a.get("defer_hours") or 0) > 0),
            "avg_confidence": round(sum(confidences) / len(confidences), 2) if confidences else None,
            "action_distribution": dict(Counter(a["action"] for a in ai_real)),
        },
        "cases": [
            {
                "signal_id": sid,
                "customer_name": c["signal"]["customer_name"],
                "type": c["signal"]["type"],
                "amount": c["signal"]["amount"],
                "outcome": c["outcome"],
                "recovered": c["recovered"],
                "ai_changed": c["refined"],
                "stages": [
                    {
                        "stage": e["stage"],
                        "label": STAGE_LABELS.get(e["stage"], e["stage"]),
                        "at": e["created_at"],
                        "payload": e["payload"],
                    }
                    for e in c["stages"]
                ],
            }
            # AI-overridden cases first: the one place the model overruled the
            # rules engine is the thing a reviewer most wants to find.
            for sid, c in sorted(cases.items(),
                                 key=lambda kv: (not kv[1]["refined"], -kv[1]["signal"]["amount"]))
        ],
    }
