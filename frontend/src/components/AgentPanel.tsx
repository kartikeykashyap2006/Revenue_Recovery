import type { AgentStats, RunConfig } from "../types";
import { Stat } from "./Stat";

interface Props {
  agent: AgentStats;
  config: RunConfig | null;
}

export function AgentPanel({ agent, config }: Props) {
  if (!config?.use_ai_recovery_agent) {
    return (
      <section className="card">
        <h2>What the AI agent actually did</h2>
        <div className="stats">
          <Stat label="Consultations" value="0" sub="USE_AI_RECOVERY_AGENT is off" />
        </div>
      </section>
    );
  }
  if (!agent.consultations) {
    return (
      <section className="card">
        <h2>What the AI agent actually did</h2>
        <div className="stats">
          <Stat
            label="Consultations"
            value="0"
            sub={`agent is on (${config.llm_provider}) -- no signal in this run cleared every guardrail`}
          />
        </div>
      </section>
    );
  }
  return (
    <section className="card">
      <h2>What the AI agent actually did</h2>
      <div className="stats">
        <Stat
          label="Consultations"
          value={String(agent.consultations)}
          sub="only signals that cleared every guardrail"
        />
        <Stat
          label="Real model answers"
          value={`${agent.real_answers} of ${agent.consultations}`}
          sub={`${agent.fallbacks} fell back safely`}
        />
        <Stat
          label="Changed the outcome"
          value={String(agent.changed_outcome)}
          sub="overrode the deterministic decision"
        />
        <Stat
          label="Chose the channel"
          value={String(agent.chose_channel)}
          sub="only where contact history justified it"
        />
      </div>
    </section>
  );
}
