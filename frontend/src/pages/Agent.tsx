import { useDashboard } from "../context/DashboardContext";
import { AgentPanel } from "../components/AgentPanel";
import { OUTCOME_COLOR } from "../format";
import type { Case } from "../types";

interface AiPayload {
  action?: string;
  confidence?: number;
  reasoning?: string;
  channel?: string | null;
  defer_hours?: number | null;
  error?: string;
}

function ReasoningCard({ item }: { item: Case }) {
  const stage = item.stages.find((s) => s.stage === "ai_recommendation");
  if (!stage) return null;
  const p = stage.payload as AiPayload;

  return (
    <div className="reasoning-card">
      <div className="reasoning-head">
        <span className="chip">
          <i className="dot" style={{ background: OUTCOME_COLOR[item.outcome] ?? "var(--muted)" }} />
          {item.outcome}
        </span>
        <strong>{item.customer_name}</strong>
        <span className="mono dim">{item.type}</span>
      </div>
      {p.reasoning && <p className="reasoning-text">&ldquo;{p.reasoning}&rdquo;</p>}
      <div className="reasoning-meta">
        <span>
          model said <b>{p.action}</b>
        </span>
        {p.confidence != null && <span>confidence {Math.round(p.confidence * 100)}%</span>}
        {p.channel && <span>channel → {p.channel}</span>}
        {!!p.defer_hours && <span>deferred {p.defer_hours}h</span>}
        {p.error && <span className="warn">fell back: {p.error}</span>}
      </div>
    </div>
  );
}

export function Agent() {
  const { ready, config } = useDashboard();
  const data = ready!;
  const overridden = data.cases.filter((c) => c.ai_changed);

  return (
    <>
      <AgentPanel agent={data.agent} config={config} />

      <section className="card">
        <h2>Where the AI changed the outcome</h2>
        {overridden.length === 0 ? (
          <p className="note">
            No consultation in this run overrode the deterministic decision -- try a larger batch, or one with a
            different seed, to see a <code>hold</code>/<code>escalate</code> override in practice.
          </p>
        ) : (
          <div className="reasoning-list">
            {overridden.map((c) => (
              <ReasoningCard item={c} key={c.signal_id} />
            ))}
          </div>
        )}
        <p className="note">
          Every consultation is logged as its own <code>ai_recommendation</code> audit event, whether or not it
          changed anything -- these are the ones that did. See the Cases page for the full trail on any signal.
        </p>
      </section>
    </>
  );
}
