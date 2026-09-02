import { useState } from "react";
import type { Case } from "../types";
import { OUTCOME_COLOR, rupees, timeOnly } from "../format";

interface Props {
  cases: Case[];
}

function Trace({ item }: { item: Case }) {
  return (
    <div className="trace">
      {item.stages.map((stage, i) => (
        <div
          className={`stage${stage.stage === "decision_ai_refined" ? " refined" : ""}`}
          key={`${stage.stage}-${i}`}
        >
          <div className="stage-head">
            <span className="stage-name">{stage.label}</span>
            <span className="stage-time">{timeOnly(stage.at)}</span>
          </div>
          <pre>{JSON.stringify(stage.payload, null, 2)}</pre>
        </div>
      ))}
    </div>
  );
}

/**
 * The centrepiece: every case, one click from its complete audit trail. Cases
 * the AI overrode are already first in the payload, because that is the row a
 * reviewer most wants to find.
 */
export function CaseList({ cases }: Props) {
  const [open, setOpen] = useState<string | null>(null);

  return (
    <section className="card">
      <h2>Every case, and its complete audit trail</h2>
      <div className="thead">
        <div>outcome</div>
        <div>customer</div>
        <div>scenario</div>
        <div className="amt">amount</div>
        <div>signal</div>
      </div>
      {cases.map((item) => {
        const isOpen = open === item.signal_id;
        return (
          <div className="case" key={item.signal_id}>
            <button
              className="case-summary"
              aria-expanded={isOpen}
              onClick={() => setOpen(isOpen ? null : item.signal_id)}
            >
              <span>
                <i
                  className="dot"
                  style={{ background: OUTCOME_COLOR[item.outcome] ?? "var(--muted)" }}
                />{" "}
                {item.outcome}
              </span>
              <span>
                {item.customer_name}
                {item.ai_changed && <span className="chip" style={{ marginLeft: 8 }}>AI changed this</span>}
              </span>
              <span className="mono">{item.type}</span>
              <span className="amt">{rupees(item.amount)}</span>
              <span className="mono">{item.signal_id}</span>
            </button>
            {isOpen && <Trace item={item} />}
          </div>
        );
      })}
      <p className="note">
        Every line above is read straight from the audit log — nothing here is recomputed for display.
      </p>
    </section>
  );
}
