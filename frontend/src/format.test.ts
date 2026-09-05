import { describe, expect, it } from "vitest";
import { OUTCOME_COLOR, percent, rupees, SCENARIO_COLOR, timeOnly } from "./format";

describe("rupees", () => {
  it("formats with the Rs. prefix and Indian digit grouping", () => {
    expect(rupees(1234567)).toBe("Rs. 12,34,567");
  });

  it("drops fractional paise -- the dashboard never shows sub-rupee amounts", () => {
    expect(rupees(1234.99)).toBe("Rs. 1,235");
  });

  it("handles zero without a stray sign or decimal", () => {
    expect(rupees(0)).toBe("Rs. 0");
  });
});

describe("percent", () => {
  it("converts a fraction to a one-decimal percentage", () => {
    expect(percent(0.0819)).toBe("8.2%");
  });

  it("handles a zero rate", () => {
    expect(percent(0)).toBe("0.0%");
  });

  it("handles a rate above 1 without clamping -- the backend guarantees the range, not this function", () => {
    expect(percent(1.5)).toBe("150.0%");
  });
});

describe("timeOnly", () => {
  it("extracts just the HH:MM:SS from a full ISO timestamp", () => {
    expect(timeOnly("2026-09-04T05:29:15.130239")).toBe("05:29:15");
  });
});

describe("color maps", () => {
  it("covers every scenario type the backend can send", () => {
    const scenarios = [
      "payment_failure",
      "checkout_abandonment",
      "subscription_mandate_failure",
      "overdue_receivable",
    ];
    for (const s of scenarios) {
      expect(SCENARIO_COLOR[s]).toBeTruthy();
    }
  });

  it("covers every outcome the backend can send", () => {
    const outcomes = ["recovered", "sent", "escalated", "stopped", "deferred", "failed", "skipped"];
    for (const o of outcomes) {
      expect(OUTCOME_COLOR[o]).toBeTruthy();
    }
  });
});
