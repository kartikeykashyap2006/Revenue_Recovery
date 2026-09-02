import type { ScenarioRow } from "../types";
import { SCENARIO_COLOR, rupees } from "../format";

interface Props {
  rows: ScenarioRow[];
}

/**
 * Bar length is the amount at stake so scenarios stay comparable; the solid
 * segment is confirmed recovery within it. Every row carries a direct label,
 * which is also the documented relief for the two light-mode palette slots
 * that sit below 3:1 contrast.
 */
export function ScenarioBars({ rows }: Props) {
  const max = Math.max(...rows.map((r) => r.at_risk), 1);
  return (
    <section className="card">
      <h2>Recovery by scenario</h2>
      <div className="legend">
        {rows.map((r) => (
          <span key={r.type}>
            <i className="dot" style={{ background: SCENARIO_COLOR[r.type] ?? "var(--muted)" }} />
            {r.type}
          </span>
        ))}
      </div>
      {rows.map((r) => {
        const color = SCENARIO_COLOR[r.type] ?? "var(--muted)";
        const totalWidth = (r.at_risk / max) * 100;
        const recoveredShare = r.at_risk ? (r.recovered / r.at_risk) * 100 : 0;
        return (
          <div
            className="row"
            key={r.type}
            title={`${r.type}: ${r.count} signals, ${rupees(r.recovered)} recovered of ${rupees(r.at_risk)} at risk`}
          >
            <div className="row-label">
              {r.type} <span className="dim">({r.count})</span>
            </div>
            <div className="track">
              <div className="seg-wrap" style={{ width: `${Math.max(totalWidth, 0.6)}%` }}>
                <div className="seg-rec" style={{ width: `${recoveredShare}%`, background: color }} />
                <div className="seg-risk" style={{ background: color }} />
              </div>
            </div>
            <div className="row-value">
              {rupees(r.recovered)}{" "}
              <span className="dim">
                of {rupees(r.at_risk)} ({(r.rate * 100).toFixed(0)}%)
              </span>
            </div>
          </div>
        );
      })}
      <p className="note">
        Solid = confirmed recovered. Pale = still at risk. Bar length is the amount at stake.
      </p>
    </section>
  );
}
