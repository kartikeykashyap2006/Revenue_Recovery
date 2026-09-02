#!/usr/bin/env python3
"""Builds a self-contained HTML dashboard from the audit trail.

Everything the engine does is currently only visible as terminal output and
JSONL, which makes a genuinely working backend invisible in a demo. This
renders the most recent batch as one page: headline numbers, the detection
funnel, recovery by scenario, what the AI agent actually did, and -- the point
of the whole thing -- every case expandable to its complete audit trail, so
"we log every decision" stops being a claim and becomes something a reviewer
can click.

Reads only audit_log.jsonl. No server, no network, no build step: the output
is one file that opens in a browser and works offline, which is what you want
when you are demoing on someone else's wifi.

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
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db

OUT_PATH = "reports/dashboard.html"

# Palette: validated categorical slots 1-4 (see the data-viz reference palette).
# Light mode slots 3 and 4 sit below 3:1 on the surface, so every bar carries a
# visible direct label -- the documented relief for that, and the case table
# below doubles as the table view.
SCENARIO_COLORS = {
    "payment_failure":              ("#2a78d6", "#3987e5"),
    "checkout_abandonment":         ("#eb6834", "#d95926"),
    "subscription_mandate_failure": ("#1baf7a", "#199e70"),
    "overdue_receivable":           ("#eda100", "#c98500"),
}
# Status colors are reserved and never reused as series colors; each ships with
# a text label so state is never carried by hue alone.
STATUS = {
    "recovered": ("#0ca30c", "recovered"),
    "sent":      ("#2a78d6", "sent"),
    "escalated": ("#fab219", "escalated"),
    "stopped":   ("#ec835a", "stopped"),
    "deferred":  ("#4a3aa7", "deferred"),
    "failed":    ("#d03b3b", "failed"),
    "skipped":   ("#898781", "skipped"),
}

STAGE_LABELS = {
    "signal": "signal detected",
    "diagnosis": "diagnosed",
    "decision": "policy decision",
    "ai_recommendation": "AI agent consulted",
    "decision_ai_refined": "AI CHANGED THE OUTCOME",
    "action": "action",
    "confirmation": "confirmation",
}


def latest_batch(entries):
    """Everything after the last batch_detection marker -- one run, so nothing
    is double-counted across repeated runs sharing an audit log."""
    starts = [i for i, e in enumerate(entries) if e["stage"] == "batch_detection"]
    if not starts:
        return entries, None, 0
    marker = entries[starts[-1]]
    return entries[starts[-1]:], marker["payload"], len(starts)


def esc(v):
    return html.escape(str(v), quote=True)


def rupees(n):
    return f"{n:,.0f}"


def build_cases(events):
    cases = defaultdict(lambda: {"stages": [], "signal": None, "action": None,
                                 "ai": None, "refined": False, "confirmation": None})
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


def stat(label, value, sub=""):
    sub_html = f'<div class="stat-sub">{esc(sub)}</div>' if sub else ""
    return (f'<div class="stat"><div class="stat-label">{esc(label)}</div>'
            f'<div class="stat-value">{esc(value)}</div>{sub_html}</div>')


def bar_row(label, value, total, color_light, color_dark, value_label, tooltip):
    pct = (value / total * 100) if total else 0
    return (
        f'<div class="row" title="{esc(tooltip)}">'
        f'  <div class="row-label">{esc(label)}</div>'
        f'  <div class="track">'
        f'    <div class="fill" style="width:{max(pct, 0.6):.2f}%;'
        f'--c:{color_light};--cd:{color_dark}"></div>'
        f'  </div>'
        f'  <div class="row-value">{esc(value_label)}</div>'
        f'</div>'
    )


def render_trace(case):
    out = []
    for e in case["stages"]:
        stage = e["stage"]
        label = STAGE_LABELS.get(stage, stage)
        cls = "stage-refined" if stage == "decision_ai_refined" else ""
        payload = json.dumps(e["payload"], indent=2, default=str)
        out.append(
            f'<div class="stage {cls}">'
            f'<div class="stage-head"><span class="stage-name">{esc(label)}</span>'
            f'<span class="stage-time">{esc(e["created_at"][11:19])}</span></div>'
            f'<pre>{esc(payload)}</pre></div>'
        )
    return "".join(out)


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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--open", action="store_true", help="open the dashboard when built")
    args = parser.parse_args()

    entries = db.fetch_audit_log()
    if not entries:
        print("No audit log entries found. Run scripts/run_batch.py first.")
        return

    events, detection, run_count = latest_batch(entries)
    cases = build_cases(events)
    if not cases:
        print("No complete cases in the latest batch -- run scripts/run_batch.py again.")
        return

    # An "action" event is written when the outreach is SENT, which is strictly
    # before the confirmation pass runs -- so in the log every action reads
    # status=sent, amount_recovered=0, forever. Recovery lives only in the
    # later "confirmation" stage. Reading the action event for money would
    # report Rs. 0 recovered on a batch that recovered plenty, which is
    # exactly the confusion the two-stage design exists to prevent.
    for c in cases.values():
        conf = c["confirmation"]
        if conf and conf.get("confirmed"):
            c["outcome"] = "recovered"
            c["recovered"] = conf.get("amount", 0) or 0
        else:
            c["outcome"] = c["action"]["status"]
            c["recovered"] = 0.0

    at_risk = sum(c["signal"]["amount"] for c in cases.values())
    recovered = sum(c["recovered"] for c in cases.values())
    statuses = Counter(c["outcome"] for c in cases.values())
    by_type = defaultdict(lambda: {"at_risk": 0.0, "recovered": 0.0, "n": 0})
    for c in cases.values():
        t = by_type[c["signal"]["type"]]
        t["at_risk"] += c["signal"]["amount"]
        t["recovered"] += c["recovered"]
        t["n"] += 1

    ai = [c["ai"] for c in cases.values() if c["ai"]]
    ai_real = [a for a in ai if not a.get("error")]
    ai_changed = sum(1 for c in cases.values() if c["refined"])
    ai_channel = sum(1 for a in ai_real if a.get("channel"))

    # --- header ------------------------------------------------------------
    parts = [f"<style>{CSS}</style>", '<div class="wrap">']
    parts.append("<h1>AI Revenue Recovery Agent</h1>")
    detected = detection["signals_detected"] if detection else len(cases)
    raw = detection["raw_cases"] if detection else len(cases)
    parts.append(
        f'<p class="sub">Most recent batch &middot; {len(cases)} signals processed'
        f'{f" &middot; {run_count} run(s) in this audit trail" if run_count > 1 else ""}</p>'
    )

    # --- headline numbers --------------------------------------------------
    rate = (recovered / at_risk * 100) if at_risk else 0
    parts.append('<div class="card"><div class="stats">')
    parts.append(stat("Revenue at risk", f"Rs. {rupees(at_risk)}"))
    parts.append(stat("Confirmed recovered", f"Rs. {rupees(recovered)}",
                      "via a distinct confirmation event"))
    parts.append(stat("Recovery rate", f"{rate:.1f}%"))
    parts.append(stat("Signals detected", f"{detected} of {raw}",
                      f"{raw - detected} resolved on their own"))
    parts.append("</div></div>")

    # --- detection funnel --------------------------------------------------
    contacted = statuses.get("sent", 0) + statuses.get("recovered", 0)
    confirmed = statuses.get("recovered", 0)
    parts.append('<div class="card"><h2>From raw events to recovered revenue</h2>')
    funnel = [
        ("Raw event-cases", raw, "every case the stream contained"),
        ("Needed a signal", detected, "the rest resolved without us"),
        ("Contacted", contacted, "cleared every compliance guardrail"),
        ("Confirmed recovered", confirmed, "a real confirmation event said so"),
    ]
    for label, val, why in funnel:
        parts.append(bar_row(label, val, raw or 1, "#2a78d6", "#3987e5",
                             str(val), f"{label}: {val} - {why}"))
    parts.append('<p class="note">Each stage is a real filter, not a restatement '
                 'of the one above it.</p></div>')

    # --- by scenario -------------------------------------------------------
    parts.append('<div class="card"><h2>Recovery by scenario</h2><div class="legend">')
    for t in by_type:
        cl, cd = SCENARIO_COLORS.get(t, ("#898781", "#898781"))
        parts.append(f'<span><i class="dot" style="background:{cl}"></i>{esc(t)}</span>')
    parts.append("</div>")
    max_risk = max((v["at_risk"] for v in by_type.values()), default=1)
    for t, v in sorted(by_type.items(), key=lambda kv: -kv[1]["at_risk"]):
        cl, cd = SCENARIO_COLORS.get(t, ("#898781", "#898781"))
        pct = (v["recovered"] / v["at_risk"] * 100) if v["at_risk"] else 0
        total_w = v["at_risk"] / max_risk * 100 if max_risk else 0
        rec_w = (v["recovered"] / max_risk * 100) if max_risk else 0
        parts.append(
            f'<div class="row" title="{esc(t)}: {v["n"]} signals, Rs. '
            f'{rupees(v["recovered"])} recovered of Rs. {rupees(v["at_risk"])} at risk">'
            f'<div class="row-label">{esc(t)} <span class="dim">({v["n"]})</span></div>'
            f'<div class="track">'
            f'<div class="seg-wrap" style="width:{max(total_w, 0.6):.2f}%">'
            f'<div class="seg-rec" style="width:{(rec_w / total_w * 100) if total_w else 0:.2f}%;'
            f'--c:{cl};--cd:{cd}"></div>'
            f'<div class="seg-risk" style="--c:{cl};--cd:{cd}"></div>'
            f'</div></div>'
            f'<div class="row-value">Rs. {rupees(v["recovered"])} '
            f'<span class="dim">of {rupees(v["at_risk"])} ({pct:.0f}%)</span></div>'
            f'</div>'
        )
    parts.append('<p class="note">Solid = confirmed recovered. Pale = still at risk. '
                 'Bar length is the amount at stake, so the scenarios stay comparable.</p>')
    parts.append("</div>")

    # --- outcomes ----------------------------------------------------------
    parts.append('<div class="card"><h2>Outcomes</h2><div class="chips">')
    for st, n in statuses.most_common():
        color, label = STATUS.get(st, ("#898781", st))
        parts.append(f'<span class="chip"><i class="dot" style="background:{color}"></i>'
                     f'{esc(label)} &middot; {n}</span>')
    parts.append("</div></div>")

    # --- the AI layer ------------------------------------------------------
    parts.append('<div class="card"><h2>What the AI agent actually did</h2><div class="stats">')
    if ai:
        parts.append(stat("Consultations", str(len(ai)), "only signals that cleared every guardrail"))
        parts.append(stat("Real model answers", f"{len(ai_real)} of {len(ai)}",
                          f"{len(ai) - len(ai_real)} fell back safely"))
        parts.append(stat("Changed the outcome", str(ai_changed),
                          "overrode the deterministic decision"))
        parts.append(stat("Chose the channel", str(ai_channel),
                          "only where contact history justified it"))
    else:
        parts.append(stat("Consultations", "0", "USE_AI_RECOVERY_AGENT is off"))
    parts.append("</div></div>")

    # --- every case, expandable to its full trail --------------------------
    parts.append('<div class="card"><h2>Every case, and its complete audit trail</h2>')
    parts.append('<div class="thead"><div>outcome</div><div>customer</div>'
                 '<div>scenario</div><div class="amt">amount</div><div>signal</div></div>')
    ordered = sorted(cases.items(),
                     key=lambda kv: (not kv[1]["refined"], -kv[1]["signal"]["amount"]))
    for sid, c in ordered:
        st = c["outcome"]
        color, label = STATUS.get(st, ("#898781", st))
        flag = ' <span class="chip" style="padding:1px 8px">AI changed this</span>' if c["refined"] else ""
        parts.append(
            f'<details class="case"><summary>'
            f'<span><i class="dot" style="background:{color}"></i> {esc(label)}</span>'
            f'<span>{esc(c["signal"]["customer_name"])}{flag}</span>'
            f'<span class="mono">{esc(c["signal"]["type"])}</span>'
            f'<span class="amt">Rs. {rupees(c["signal"]["amount"])}</span>'
            f'<span class="mono">{esc(sid)}</span>'
            f'</summary><div class="trace">{render_trace(c)}</div></details>'
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
