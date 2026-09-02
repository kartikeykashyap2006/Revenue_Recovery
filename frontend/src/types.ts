/**
 * Mirrors the payload from the backend's app/reporting/dashboard_data.py.
 *
 * Kept as one file so a backend change that breaks the contract shows up as a
 * type error here rather than as `undefined` rendered into the page.
 */

export type Outcome =
  | "recovered"
  | "sent"
  | "escalated"
  | "stopped"
  | "deferred"
  | "failed"
  | "skipped";

export type ScenarioType =
  | "payment_failure"
  | "checkout_abandonment"
  | "subscription_mandate_failure"
  | "overdue_receivable";

/** One audit-trail entry: what happened to a signal, when, with its payload. */
export interface Stage {
  stage: string;
  label: string;
  at: string;
  payload: Record<string, unknown>;
}

export interface Case {
  signal_id: string;
  customer_name: string;
  type: ScenarioType | string;
  amount: number;
  outcome: Outcome | string;
  recovered: number;
  /** True when the AI agent overrode the deterministic decision. */
  ai_changed: boolean;
  stages: Stage[];
}

export interface Totals {
  signals: number;
  at_risk: number;
  /** Only ever money backed by a confirmation event, never "we sent something". */
  recovered: number;
  recovery_rate: number;
}

export interface Detection {
  raw_cases: number;
  signals_detected: number;
  resolved_on_their_own: number;
}

export interface FunnelStep {
  label: string;
  value: number;
  note: string;
}

export interface ScenarioRow {
  type: ScenarioType | string;
  count: number;
  at_risk: number;
  recovered: number;
  rate: number;
}

export interface AgentStats {
  consultations: number;
  real_answers: number;
  fallbacks: number;
  changed_outcome: number;
  chose_channel: number;
  postponed: number;
  avg_confidence: number | null;
  action_distribution: Record<string, number>;
}

export interface Dashboard {
  empty: false;
  runs_in_log: number;
  totals: Totals;
  detection: Detection;
  funnel: FunnelStep[];
  by_scenario: ScenarioRow[];
  outcomes: Partial<Record<Outcome, number>> & Record<string, number>;
  agent: AgentStats;
  cases: Case[];
}

export interface EmptyDashboard {
  empty: true;
  reason: string;
}

export type DashboardResponse = Dashboard | EmptyDashboard;
