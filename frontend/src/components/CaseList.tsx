import { useEffect, useMemo, useState } from "react";
import type { Case } from "../types";
import { OUTCOME_COLOR, rupees, timeOnly } from "../format";

interface Props {
  cases: Case[];
}

const PAGE_SIZE = 25;

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
function toggle<T>(set: Set<T>, value: T): Set<T> {
  const next = new Set(set);
  next.has(value) ? next.delete(value) : next.add(value);
  return next;
}

export function CaseList({ cases }: Props) {
  const [open, setOpen] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [outcomes, setOutcomes] = useState<Set<string>>(new Set());
  const [types, setTypes] = useState<Set<string>>(new Set());
  const [aiOnly, setAiOnly] = useState(false);
  const [visible, setVisible] = useState(PAGE_SIZE);

  const outcomeOptions = useMemo(
    () => [...new Set(cases.map((c) => c.outcome))].sort(),
    [cases],
  );
  const typeOptions = useMemo(
    () => [...new Set(cases.map((c) => c.type))].sort(),
    [cases],
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return cases.filter((c) => {
      if (outcomes.size && !outcomes.has(c.outcome)) return false;
      if (types.size && !types.has(c.type)) return false;
      if (aiOnly && !c.ai_changed) return false;
      if (q && !(c.customer_name.toLowerCase().includes(q) || c.signal_id.toLowerCase().includes(q))) {
        return false;
      }
      return true;
    });
  }, [cases, query, outcomes, types, aiOnly]);

  // Any filter change should re-show from the top rather than leaving the
  // page cut off mid-list from a larger, now-stale result set.
  useEffect(() => setVisible(PAGE_SIZE), [query, outcomes, types, aiOnly]);

  const hasFilters = query.trim() !== "" || outcomes.size > 0 || types.size > 0 || aiOnly;
  const shown = filtered.slice(0, visible);

  return (
    <section className="card">
      <h2>Every case, and its complete audit trail</h2>

      <div className="case-filters">
        <input
          className="search"
          type="search"
          placeholder="search customer or signal id"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="search cases"
        />
        <div className="chips">
          {outcomeOptions.map((o) => (
            <button
              key={o}
              type="button"
              className={`chip filter-chip${outcomes.has(o) ? " active" : ""}`}
              onClick={() => setOutcomes((s) => toggle(s, o))}
              aria-pressed={outcomes.has(o)}
            >
              <i className="dot" style={{ background: OUTCOME_COLOR[o] ?? "var(--muted)" }} />
              {o}
            </button>
          ))}
          {typeOptions.map((t) => (
            <button
              key={t}
              type="button"
              className={`chip filter-chip${types.has(t) ? " active" : ""}`}
              onClick={() => setTypes((s) => toggle(s, t))}
              aria-pressed={types.has(t)}
            >
              {t}
            </button>
          ))}
          <button
            type="button"
            className={`chip filter-chip${aiOnly ? " active" : ""}`}
            onClick={() => setAiOnly((v) => !v)}
            aria-pressed={aiOnly}
          >
            AI changed this
          </button>
          {hasFilters && (
            <button
              type="button"
              className="chip filter-chip clear"
              onClick={() => {
                setQuery("");
                setOutcomes(new Set());
                setTypes(new Set());
                setAiOnly(false);
              }}
            >
              clear filters
            </button>
          )}
        </div>
      </div>

      <div className="thead">
        <div>outcome</div>
        <div>customer</div>
        <div>scenario</div>
        <div className="amt">amount</div>
        <div>signal</div>
      </div>
      {shown.length === 0 && <p className="note">No cases match these filters.</p>}
      {shown.map((item) => {
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

      {filtered.length > visible && (
        <button type="button" className="link-btn show-more" onClick={() => setVisible((v) => v + PAGE_SIZE)}>
          Show {Math.min(PAGE_SIZE, filtered.length - visible)} more ({filtered.length - visible} left)
        </button>
      )}

      <p className="note">
        Showing {shown.length} of {filtered.length}
        {filtered.length !== cases.length ? ` (filtered from ${cases.length})` : ""} — every line above is
        read straight from the audit log, nothing here is recomputed for display.
      </p>
    </section>
  );
}
