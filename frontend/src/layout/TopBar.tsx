import { useDashboard } from "../context/DashboardContext";
import { IconChevron, IconPlay } from "./icons";

interface Props {
  title: string;
  subtitle?: string;
}

export function TopBar({ title, subtitle }: Props) {
  const {
    ready,
    config,
    busy,
    size,
    setSize,
    seed,
    setSeed,
    simulateTime,
    setSimulateTime,
    showControls,
    setShowControls,
    runNow,
  } = useDashboard();

  return (
    <header className="topbar">
      <div className="topbar-row">
        <div className="topbar-title">
          <h1>{title}</h1>
          <p className="topbar-sub">
            {subtitle ??
              (ready
                ? `Most recent batch · ${ready.totals.signals} signals processed` +
                  (ready.runs_in_log > 1 ? ` · ${ready.runs_in_log} runs in this audit trail` : "")
                : "Detects revenue at risk, decides what to do, and proves what came back.")}
          </p>
        </div>

        <div className="topbar-actions">
          {config && (
            <span className={`chip agent-chip ${config.use_ai_recovery_agent ? "on" : "off"}`}>
              <i className="dot" style={{ background: config.use_ai_recovery_agent ? "var(--status-good)" : "var(--muted)" }} />
              AI agent {config.use_ai_recovery_agent ? `on · ${config.llm_provider}` : "off"}
            </span>
          )}
          <button
            type="button"
            className="ghost-btn"
            onClick={() => setShowControls((s) => !s)}
            aria-expanded={showControls}
          >
            Run options
            <IconChevron className={`chev${showControls ? " up" : ""}`} />
          </button>
          <input
            className="n"
            type="number"
            min={1}
            max={200}
            value={size}
            aria-label="batch size"
            onChange={(e) => setSize(Number(e.target.value))}
          />
          <button className="action" onClick={runNow} disabled={busy}>
            {!busy && <IconPlay className="btn-icon" />}
            {busy ? "Running…" : "Run batch"}
          </button>
        </div>
      </div>

      {showControls && (
        <div className="run-options">
          <label>
            seed
            <input type="number" placeholder="random" value={seed} onChange={(e) => setSeed(e.target.value)} />
          </label>
          <label>
            simulate now (UTC)
            <input type="datetime-local" value={simulateTime} onChange={(e) => setSimulateTime(e.target.value)} />
          </label>
          <span className="note run-options-note">
            Reproduces a specific run (same seed) at a specific clock time -- e.g. to demo cooldown or
            promise-to-pay follow-up, run once, note the seed, then run again with a later time.
          </span>
        </div>
      )}
    </header>
  );
}
