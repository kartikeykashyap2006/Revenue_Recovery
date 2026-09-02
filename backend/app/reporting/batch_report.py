"""Aggregate batch-level reporting: measured money recovered, broken down
by scenario type and root cause, plus compliance/escalation stats."""
import json
import os
from collections import defaultdict
from typing import List

from app.models import Trace, ActionStatus


def generate_report(traces: List[Trace]) -> dict:
    total_at_risk = sum(t.signal.amount for t in traces)
    total_recovered = sum(t.action.amount_recovered for t in traces)

    by_type = defaultdict(lambda: {"count": 0, "at_risk": 0.0, "recovered": 0.0})
    by_root_cause = defaultdict(lambda: {"count": 0, "recovered": 0.0})
    status_counts = defaultdict(int)

    for t in traces:
        key = t.signal.type.value
        by_type[key]["count"] += 1
        by_type[key]["at_risk"] += t.signal.amount
        by_type[key]["recovered"] += t.action.amount_recovered

        cause_key = t.diagnosis.root_cause.value
        by_root_cause[cause_key]["count"] += 1
        by_root_cause[cause_key]["recovered"] += t.action.amount_recovered

        status_counts[t.action.status.value] += 1

    return {
        "batch_size": len(traces),
        "total_at_risk_amount": round(total_at_risk, 2),
        "total_recovered_amount": round(total_recovered, 2),
        "recovery_rate": round(total_recovered / total_at_risk, 4) if total_at_risk else 0.0,
        "by_scenario_type": {
            k: {"count": v["count"], "at_risk": round(v["at_risk"], 2), "recovered": round(v["recovered"], 2)}
            for k, v in by_type.items()
        },
        "by_root_cause": {
            k: {"count": v["count"], "recovered": round(v["recovered"], 2)}
            for k, v in by_root_cause.items()
        },
        "action_status_counts": dict(status_counts),
        "escalated_count": status_counts.get(ActionStatus.ESCALATED.value, 0),
        "stopped_count": status_counts.get(ActionStatus.STOPPED.value, 0),
    }


def print_report(report: dict) -> None:
    try:
        from rich.console import Console
        from rich.table import Table

        console = Console()
        console.print(f"\n[bold]Batch size:[/bold] {report['batch_size']}")
        console.print(f"[bold]Total at risk:[/bold] Rs. {report['total_at_risk_amount']:,.2f}")
        console.print(f"[bold]Total recovered:[/bold] Rs. {report['total_recovered_amount']:,.2f}")
        console.print(f"[bold]Recovery rate:[/bold] {report['recovery_rate']*100:.1f}%\n")

        table = Table(title="By scenario type")
        table.add_column("Type")
        table.add_column("Count", justify="right")
        table.add_column("At risk (Rs.)", justify="right")
        table.add_column("Recovered (Rs.)", justify="right")
        for k, v in report["by_scenario_type"].items():
            table.add_row(k, str(v["count"]), f"{v['at_risk']:,.2f}", f"{v['recovered']:,.2f}")
        console.print(table)

        console.print(f"\n[bold]Action outcomes:[/bold] {report['action_status_counts']}")
    except ImportError:
        print(json.dumps(report, indent=2))


def save_report(report: dict, path: str = "reports/latest_report.json") -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(report, f, indent=2)
