import { useCallback, useEffect, useState } from "react";
import { BackendUnreachable, fetchDashboard, runBatch } from "./api";
import type { DashboardResponse } from "./types";
import { OUTCOME_COLOR, percent, rupees } from "./format";
import { Stat } from "./components/Stat";
import { Funnel } from "./components/Funnel";
import { ScenarioBars } from "./components/ScenarioBars";
import { AgentPanel } from "./components/AgentPanel";
import { CaseList } from "./components/CaseList";

export default function App() {
  const [data, setData] = useState<DashboardResponse | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [busy, setBusy] = useState(false);
  const [size, setSize] = useState(25);

  const load = useCallback(async () => {
    try {
      setError(null);
      setData(await fetchDashboard());
    } catch (e) {
      setError(e as Error);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const onRun = async () => {
    setBusy(true);
    try {
      setError(null);
      // A batch with the agent enabled makes a real model call per cleared
      // signal, so this can take a few seconds -- the button stays disabled
      // rather than letting a second run pile onto the first.
      setData(await runBatch({ n: size, simulateTime: "2026-08-31T10:00:00" }));
    } catch (e) {
      setError(e as Error);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="wrap">
      <header className="top">
        <div>
          <h1>AI Revenue Recovery Agent</h1>
          <p className="sub">
            {data && !data.empty
              ? `Most recent batch · ${data.totals.signals} signals processed` +
                (data.runs_in_log > 1 ? ` · ${data.runs_in_log} runs in this audit trail` : "")
              : "Detects revenue at risk, decides what to do, and proves what came back."}
          </p>
        </div>
        <div className="controls">
          <input
            className="n"
            type="number"
            min={1}
            max={200}
            value={size}
            aria-label="batch size"
            onChange={(e) => setSize(Number(e.target.value))}
          />
          <button className="action" onClick={onRun} disabled={busy}>
            {busy ? "Running…" : "Run batch"}
          </button>
        </div>
      </header>

      {error && (
        <div className="card state error">
          <strong>{error.message}</strong>
          {error instanceof BackendUnreachable && (
            <p className="note">
              From the project root: <code>cd backend &amp;&amp; uvicorn app.main:app --reload</code>
            </p>
          )}
        </div>
      )}

      {!data && !error && <div className="state">Loading…</div>}

      {data?.empty && (
        <div className="card state">
          <strong>Nothing to show yet.</strong>
          <p className="note">{data.reason} — press “Run batch” above, or run a batch from the CLI.</p>
        </div>
      )}

      {data && !data.empty && (
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

          <AgentPanel agent={data.agent} />
          <CaseList cases={data.cases} />
        </>
      )}
    </div>
  );
}
