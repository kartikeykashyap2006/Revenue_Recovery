import type { FunnelStep } from "../types";

interface Props {
  steps: FunnelStep[];
}

export function Funnel({ steps }: Props) {
  const max = steps[0]?.value || 1;
  return (
    <section className="card">
      <h2>From raw events to recovered revenue</h2>
      {steps.map((step) => (
        <div className="row" key={step.label} title={`${step.label}: ${step.value} — ${step.note}`}>
          <div className="row-label">{step.label}</div>
          <div className="track">
            <div
              className="fill"
              style={{
                width: `${Math.max((step.value / max) * 100, 0.6)}%`,
                background: "var(--series-1)",
              }}
            />
          </div>
          <div className="row-value">{step.value}</div>
        </div>
      ))}
      <p className="note">Each stage is a real filter, not a restatement of the one above it.</p>
    </section>
  );
}
