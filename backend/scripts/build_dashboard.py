#!/usr/bin/env python3
"""Renders the latest batch as one self-contained HTML file.

This is the offline surface: no server, no network, no build step -- it opens
from disk and works on conference wifi. The React/TypeScript frontend renders
the same numbers from the same source (app/reporting/dashboard_data.py), so
the two can never disagree about a run.

Usage:
    python scripts/build_dashboard.py            # -> reports/dashboard.html
    python scripts/build_dashboard.py --open     # also open it
"""
import argparse
import html
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.reporting.dashboard_data import build_payload

OUT_PATH = "reports/dashboard.html"

# Validated categorical slots 1-4. The two light-mode slots below 3:1 contrast
# carry visible direct labels (the documented relief), and the case table
# doubles as the table view.
SCENARIO_COLORS = {
    "payment_failure":              ("#2a78d6", "#3987e5"),
    "checkout_abandonment":         ("#eb6834", "#d95926"),
    "subscription_mandate_failure": ("#1baf7a", "#199e70"),
    "overdue_receivable":           ("#eda100", "#c98500"),
}
# Status colors are reserved, never reused as series colors, and always ship
# beside a text label so state is never carried by hue alone.
STATUS = {
    "recovered": ("#0ca30c", "recovered"),
    "sent":      ("#2a78d6", "sent"),
    "escalated": ("#fab219", "escalated"),
    "stopped":   ("#ec835a", "stopped"),
    "deferred":  ("#4a3aa7", "deferred"),
    "failed":    ("#d03b3b", "failed"),
    "skipped":   ("#898781", "skipped"),
}

CSS = """
:root{color-scheme:light;
 --plane:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;
 --grid:#e1e0d9;--border:rgba(11,11,11,0.10);--track:rgba(11,11,11,0.06);}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;
 --plane:#0d0d0d;--surface:#1a1a19;--ink:#fff;--ink2:#c3c2b7;--muted:#898781;
 --grid:#2c2c2a;--border:rgba(255,255,255,0.10);--track:rgba(255,255,255,0.08);}}
:root[data-theme="dark"]{color-scheme:dark;
 --plane:#0d0d0d;--surface:#1a1a19;--ink:#fff;--ink2:#c3c2b7;--muted:#898781;
 --grid:#2c2c2a;--border:rgba(255,255,255,0.10);--track:rgba(255,255,255,0.08);}
*{box-sizing:border-box}
body{margin:0;background:var(--plane);color:var(--ink);
 font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;padding:32px 24px 64px}
.wrap{max-width:1080px;margin:0 auto}
h1{font-size:20px;margin:0 0 4px;letter-spacing:-0.01em}
.sub{color:var(--ink2);margin:0 0 28px;font-size:13px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:10px;
 padding:20px;margin-bottom:20px}
h2{font-size:13px;text-transform:uppercase;letter-spacing:0.06em;color:var(--ink2);
 margin:0 0 16px;font-weight:600}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:16px}
.stat-label{font-size:12px;color:var(--ink2);margin-bottom:6px}
.stat-value{font-size:26px;font-weight:600;letter-spacing:-0.02em}
.stat-sub{font-size:12px;color:var(--muted);margin-top:2px}
.row{display:grid;grid-template-columns:232px 1fr auto;gap:12px;align-items:center;
 margin-bottom:10px}
.row-label{font-size:13px;color:var(--ink2)}
.row-value{font-size:13px;font-variant-numeric:tabular-nums;color:var(--ink)}
.track{background:var(--track);border-radius:4px;height:14px;overflow:hidden}
.fill{height:100%;background:var(--c);border-radius:0 4px 4px 0;min-width:3px}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]) .fill{background:var(--cd)}}
:root[data-theme="dark"] .fill{background:var(--cd)}
.seg-wrap{display:flex;height:100%;gap:2px}
.seg-rec{background:var(--c);border-radius:4px 0 0 4px;flex:none}
.seg-risk{background:var(--c);opacity:0.28;border-radius:0 4px 4px 0;flex:1}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]) .seg-rec,
 :root:not([data-theme="light"]) .seg-risk{background:var(--cd)}}
:root[data-theme="dark"] .seg-rec,:root[data-theme="dark"] .seg-risk{background:var(--cd)}
.dim{color:var(--muted);font-weight:400}
.chips{display:flex;flex-wrap:wrap;gap:8px}
.chip{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--border);
 border-radius:999px;padding:4px 11px;font-size:12px;background:var(--surface)}
.dot{width:8px;height:8px;border-radius:50%;flex:none}
details.case{border-top:1px solid var(--grid)}
details.case:last-child{border-bottom:1px solid var(--grid)}
summary{display:grid;grid-template-columns:96px 1fr 150px 110px 96px;gap:12px;
 align-items:center;padding:11px 4px;cursor:pointer;list-style:none;font-size:13px}
summary::-webkit-details-marker{display:none}
summary:hover{background:var(--track)}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px;color:var(--muted)}
.amt{text-align:right;font-variant-numeric:tabular-nums}
.trace{padding:6px 4px 18px 4px}
.stage{border-left:2px solid var(--grid);padding:0 0 0 14px;margin:0 0 10px}
.stage-refined{border-left-color:#fab219}
.stage-head{display:flex;gap:10px;align-items:baseline;margin-bottom:4px}
.stage-name{font-size:12px;font-weight:600;letter-spacing:0.02em}
.stage-refined .stage-name{color:#b07c00}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]) .stage-refined .stage-name{color:#fab219}}
.stage-time{font-size:11px;color:var(--muted);font-variant-numeric:tabular-nums}
pre{margin:0;background:var(--plane);border:1px solid var(--border);border-radius:6px;
 padding:10px 12px;font-size:11.5px;line-height:1.45;overflow-x:auto;color:var(--ink2)}
.legend{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:14px;font-size:12px;color:var(--ink2)}
.legend span{display:inline-flex;align-items:center;gap:6px}
.note{font-size:12px;color:var(--muted);margin-top:12px}
.thead{display:grid;grid-template-columns:96px 1fr 150px 110px 96px;gap:12px;
 padding:0 4px 8px;font-size:11px;text-transform:uppercase;letter-spacing:0.05em;
 color:var(--muted);border-bottom:1px solid var(--grid)}
"""


def esc(v):
    return html.escape(str(v), quote=True)


def rupees(n):
    return f"{n:,.0f}"


def stat(label, value, sub=""):
    sub_html = f'<div class="stat-sub">{esc(sub)}</div>' if sub else ""
    return (f'<div class="stat"><div class="stat-label">{esc(label)}</div>'
            f'<div class="stat-value">{esc(value)}</div>{sub_html}</div>')


def render_trace(case):
    out = []
    for s in case["stages"]:
        cls = "stage-refined" if s["stage"] == "decision_ai_refined" else ""
        payload = json.dumps(s["payload"], indent=2, default=str)
        out.append(
            f'<div class="stage {cls}">'
            f'<div class="stage-head"><span class="stage-name">{esc(s["label"])}</span>'
            f'<span class="stage-time">{esc(s["at"][11:19])}</span></div>'
            f'<pre>{esc(payload)}</pre></div>'
        )
    return "".join(out)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--open", action="store_true", help="open the dashboard when built")
    args = parser.parse_args()

    payload = build_payload()
    if payload.get("empty"):
        print(f"Nothing to render: {payload.get('reason')}")
        return

    totals, detection = payload["totals"], payload["detection"]
    agent, cases, statuses = payload["agent"], payload["cases"], payload["outcomes"]
    raw, detected = detection["raw_cases"], detection["signals_detected"]

    parts = [f"<style>{CSS}</style>", '<div class="wrap">']
    parts.append("<h1>AI Revenue Recovery Agent</h1>")
    runs = payload["runs_in_log"]
    parts.append(
        f'<p class="sub">Most recent batch &middot; {totals["signals"]} signals processed'
        f'{f" &middot; {runs} run(s) in this audit trail" if runs > 1 else ""}</p>'
    )

    parts.append('<div class="card"><div class="stats">')
    parts.append(stat("Revenue at risk", f'Rs. {rupees(totals["at_risk"])}'))
    parts.append(stat("Confirmed recovered", f'Rs. {rupees(totals["recovered"])}',
                      "via a distinct confirmation event"))
    parts.append(stat("Recovery rate", f'{totals["recovery_rate"]*100:.1f}%'))
    parts.append(stat("Signals detected", f"{detected} of {raw}",
                      f'{detection["resolved_on_their_own"]} resolved on their own'))
    parts.append("</div></div>")

    parts.append('<div class="card"><h2>From raw events to recovered revenue</h2>')
    for step in payload["funnel"]:
        pct = (step["value"] / raw * 100) if raw else 0
        parts.append(
            f'<div class="row" title="{esc(step["label"])}: {step["value"]} - {esc(step["note"])}">'
            f'<div class="row-label">{esc(step["label"])}</div>'
            f'<div class="track"><div class="fill" style="width:{max(pct, 0.6):.2f}%;'
            f'--c:#2a78d6;--cd:#3987e5"></div></div>'
            f'<div class="row-value">{step["value"]}</div></div>'
        )
    parts.append('<p class="note">Each stage is a real filter, not a restatement '
                 'of the one above it.</p></div>')

    parts.append('<div class="card"><h2>Recovery by scenario</h2><div class="legend">')
    for row in payload["by_scenario"]:
        cl, _ = SCENARIO_COLORS.get(row["type"], ("#898781", "#898781"))
        parts.append(f'<span><i class="dot" style="background:{cl}"></i>{esc(row["type"])}</span>')
    parts.append("</div>")
    max_risk = max((r["at_risk"] for r in payload["by_scenario"]), default=1)
    for row in payload["by_scenario"]:
        cl, cd = SCENARIO_COLORS.get(row["type"], ("#898781", "#898781"))
        total_w = row["at_risk"] / max_risk * 100 if max_risk else 0
        rec_w = (row["recovered"] / max_risk * 100) if max_risk else 0
        parts.append(
            f'<div class="row" title="{esc(row["type"])}: {row["count"]} signals, Rs. '
            f'{rupees(row["recovered"])} recovered of Rs. {rupees(row["at_risk"])} at risk">'
            f'<div class="row-label">{esc(row["type"])} <span class="dim">({row["count"]})</span></div>'
            f'<div class="track"><div class="seg-wrap" style="width:{max(total_w, 0.6):.2f}%">'
            f'<div class="seg-rec" style="width:{(rec_w / total_w * 100) if total_w else 0:.2f}%;'
            f'--c:{cl};--cd:{cd}"></div><div class="seg-risk" style="--c:{cl};--cd:{cd}"></div>'
            f'</div></div>'
            f'<div class="row-value">Rs. {rupees(row["recovered"])} '
            f'<span class="dim">of {rupees(row["at_risk"])} ({row["rate"]*100:.0f}%)</span></div>'
            f'</div>'
        )
    parts.append('<p class="note">Solid = confirmed recovered. Pale = still at risk. '
                 'Bar length is the amount at stake, so the scenarios stay comparable.</p></div>')

    parts.append('<div class="card"><h2>Outcomes</h2><div class="chips">')
    for st, n in sorted(statuses.items(), key=lambda kv: -kv[1]):
        color, label = STATUS.get(st, ("#898781", st))
        parts.append(f'<span class="chip"><i class="dot" style="background:{color}"></i>'
                     f'{esc(label)} &middot; {n}</span>')
    parts.append("</div></div>")

    parts.append('<div class="card"><h2>What the AI agent actually did</h2><div class="stats">')
    if agent["consultations"]:
        parts.append(stat("Consultations", str(agent["consultations"]),
                          "only signals that cleared every guardrail"))
        parts.append(stat("Real model answers",
                          f'{agent["real_answers"]} of {agent["consultations"]}',
                          f'{agent["fallbacks"]} fell back safely'))
        parts.append(stat("Changed the outcome", str(agent["changed_outcome"]),
                          "overrode the deterministic decision"))
        parts.append(stat("Chose the channel", str(agent["chose_channel"]),
                          "only where contact history justified it"))
    else:
        parts.append(stat("Consultations", "0", "USE_AI_RECOVERY_AGENT is off"))
    parts.append("</div></div>")

    parts.append('<div class="card"><h2>Every case, and its complete audit trail</h2>')
    parts.append('<div class="thead"><div>outcome</div><div>customer</div>'
                 '<div>scenario</div><div class="amt">amount</div><div>signal</div></div>')
    for case in cases:
        color, label = STATUS.get(case["outcome"], ("#898781", case["outcome"]))
        flag = (' <span class="chip" style="padding:1px 8px">AI changed this</span>'
                if case["ai_changed"] else "")
        parts.append(
            f'<details class="case"><summary>'
            f'<span><i class="dot" style="background:{color}"></i> {esc(label)}</span>'
            f'<span>{esc(case["customer_name"])}{flag}</span>'
            f'<span class="mono">{esc(case["type"])}</span>'
            f'<span class="amt">Rs. {rupees(case["amount"])}</span>'
            f'<span class="mono">{esc(case["signal_id"])}</span>'
            f'</summary><div class="trace">{render_trace(case)}</div></details>'
        )
    parts.append('<p class="note">Every line above is read straight from '
                 'audit_log.jsonl &mdash; nothing here is recomputed for display.</p>')
    parts.append("</div></div>")

    os.makedirs("reports", exist_ok=True)
    with open(OUT_PATH, "w") as f:
        f.write("<!doctype html><html lang='en'><head><meta charset='utf-8'>"
                "<meta name='viewport' content='width=device-width,initial-scale=1'>"
                "<title>AI Revenue Recovery Agent</title></head><body>"
                + "".join(parts) + "</body></html>")

    print(f"Dashboard written to {OUT_PATH} ({os.path.getsize(OUT_PATH) // 1024} KB, "
          f"{len(cases)} cases). Open it in a browser -- no server needed.")
    if args.open:
        subprocess.run(["open" if sys.platform == "darwin" else "xdg-open", OUT_PATH])


if __name__ == "__main__":
    main()
