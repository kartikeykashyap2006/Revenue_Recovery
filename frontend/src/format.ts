export const rupees = (n: number): string =>
  `Rs. ${n.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;

export const percent = (fraction: number): string => `${(fraction * 100).toFixed(1)}%`;

export const timeOnly = (iso: string): string => iso.slice(11, 19);

/**
 * Validated categorical slots 1-4, light and dark. Both modes were checked with
 * the palette validator (worst adjacent CVD dE 9.1 light / 8.4 dark); the two
 * light-mode slots under 3:1 contrast always carry a visible direct label.
 */
export const SCENARIO_COLOR: Record<string, string> = {
  payment_failure: "var(--series-1)",
  checkout_abandonment: "var(--series-2)",
  subscription_mandate_failure: "var(--series-3)",
  overdue_receivable: "var(--series-4)",
};

/** Status colors are reserved and always paired with a text label. */
export const OUTCOME_COLOR: Record<string, string> = {
  recovered: "var(--status-good)",
  sent: "var(--series-1)",
  escalated: "var(--status-warning)",
  stopped: "var(--status-serious)",
  deferred: "var(--series-7)",
  failed: "var(--status-critical)",
  skipped: "var(--muted)",
};
