import { useDashboard } from "../context/DashboardContext";
import { Stat } from "../components/Stat";
import { Funnel } from "../components/Funnel";
import { ScenarioBars } from "../components/ScenarioBars";
import { OUTCOME_COLOR, percent, rupees } from "../format";

export function Overview() {
  const { ready } = useDashboard();
  const data = ready!; // AppShell only renders this route once a batch has loaded

  return (
    <>
      <section className="card">
        <div className="stats">
          <Stat label="Revenue at risk" value={rupees(data.totals.at_risk)} />
          <Stat
            label="Confirmed recovered"
            value={rupees(data.totals.recovered)}
            sub="via a distinct confirmation event"
          />
          <Stat label="Recovery rate" value={percent(data.totals.recovery_rate)} />
          <Stat
            label="Signals detected"
            value={`${data.detection.signals_detected} of ${data.detection.raw_cases}`}
            sub={`${data.detection.resolved_on_their_own} resolved on their own`}
          />
        </div>
      </section>

      <Funnel steps={data.funnel} />
      <ScenarioBars rows={data.by_scenario} />

      <section className="card">
        <h2>Outcomes</h2>
        <div className="chips">
          {Object.entries(data.outcomes)
            .sort((a, b) => b[1] - a[1])
            .map(([outcome, count]) => (
              <span className="chip" key={outcome}>
                <i className="dot" style={{ background: OUTCOME_COLOR[outcome] ?? "var(--muted)" }} />
                {outcome} · {count}
              </span>
            ))}
        </div>
      </section>
    </>
  );
}
