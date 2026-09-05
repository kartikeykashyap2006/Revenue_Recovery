import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CaseList } from "./CaseList";
import type { Case } from "../types";

function makeCase(overrides: Partial<Case>): Case {
  return {
    signal_id: "sig0",
    customer_name: "Test Customer",
    type: "payment_failure",
    amount: 1000,
    outcome: "sent",
    recovered: 0,
    ai_changed: false,
    stages: [
      { stage: "signal", label: "signal detected", at: "2026-08-31T10:00:00", payload: { amount: 1000 } },
    ],
    ...overrides,
  };
}

const CASES: Case[] = [
  makeCase({ signal_id: "s1", customer_name: "Arjun Verma", outcome: "escalated", type: "overdue_receivable", ai_changed: true }),
  makeCase({ signal_id: "s2", customer_name: "Reyansh Sharma", outcome: "sent", type: "overdue_receivable" }),
  makeCase({ signal_id: "s3", customer_name: "Krishna Iyer", outcome: "recovered", type: "payment_failure" }),
  makeCase({ signal_id: "s4", customer_name: "Meera Sharma", outcome: "sent", type: "checkout_abandonment" }),
];

describe("CaseList", () => {
  it("renders every case by default", () => {
    render(<CaseList cases={CASES} />);
    for (const c of CASES) {
      expect(screen.getByText(c.customer_name)).toBeInTheDocument();
    }
    expect(screen.getByText(/Showing 4 of 4/)).toBeInTheDocument();
  });

  it("filters by customer name, case-insensitively", async () => {
    const user = userEvent.setup();
    render(<CaseList cases={CASES} />);
    await user.type(screen.getByLabelText("search cases"), "sharma");

    expect(screen.getByText("Reyansh Sharma")).toBeInTheDocument();
    expect(screen.getByText("Meera Sharma")).toBeInTheDocument();
    expect(screen.queryByText("Arjun Verma")).not.toBeInTheDocument();
    expect(screen.queryByText("Krishna Iyer")).not.toBeInTheDocument();
  });

  it("filters by signal id", async () => {
    const user = userEvent.setup();
    render(<CaseList cases={CASES} />);
    await user.type(screen.getByLabelText("search cases"), "s3");

    expect(screen.getByText("Krishna Iyer")).toBeInTheDocument();
    expect(screen.queryByText("Arjun Verma")).not.toBeInTheDocument();
  });

  it("filters by outcome when a chip is clicked", async () => {
    const user = userEvent.setup();
    render(<CaseList cases={CASES} />);
    await user.click(screen.getByRole("button", { name: /^escalated$/ }));

    expect(screen.getByText("Arjun Verma")).toBeInTheDocument();
    expect(screen.queryByText("Reyansh Sharma")).not.toBeInTheDocument();
    expect(screen.queryByText("Krishna Iyer")).not.toBeInTheDocument();
  });

  it("filters by scenario type when a chip is clicked", async () => {
    const user = userEvent.setup();
    render(<CaseList cases={CASES} />);
    await user.click(screen.getByRole("button", { name: "checkout_abandonment" }));

    expect(screen.getByText("Meera Sharma")).toBeInTheDocument();
    expect(screen.queryByText("Arjun Verma")).not.toBeInTheDocument();
  });

  it("filters to only AI-changed cases", async () => {
    const user = userEvent.setup();
    render(<CaseList cases={CASES} />);
    await user.click(screen.getByRole("button", { name: "AI changed this" }));

    expect(screen.getByText("Arjun Verma")).toBeInTheDocument();
    expect(screen.queryByText("Reyansh Sharma")).not.toBeInTheDocument();
  });

  it("combines an outcome filter and a search term with AND, not OR", async () => {
    const user = userEvent.setup();
    render(<CaseList cases={CASES} />);
    await user.click(screen.getByRole("button", { name: /^sent$/ }));
    await user.type(screen.getByLabelText("search cases"), "sharma");

    // Reyansh Sharma is sent+sharma; Meera Sharma is also sent+sharma; Arjun
    // Verma is escalated (excluded by the outcome filter even though it's
    // not a name match anyway).
    expect(screen.getByText("Reyansh Sharma")).toBeInTheDocument();
    expect(screen.getByText("Meera Sharma")).toBeInTheDocument();
    expect(screen.queryByText("Krishna Iyer")).not.toBeInTheDocument();
  });

  it("shows a clear-filters chip only once a filter is active, and it resets everything", async () => {
    const user = userEvent.setup();
    render(<CaseList cases={CASES} />);
    expect(screen.queryByRole("button", { name: "clear filters" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "AI changed this" }));
    expect(screen.getByRole("button", { name: "clear filters" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "clear filters" }));
    expect(screen.queryByRole("button", { name: "clear filters" })).not.toBeInTheDocument();
    for (const c of CASES) {
      expect(screen.getByText(c.customer_name)).toBeInTheDocument();
    }
  });

  it("shows a no-match message when filters exclude every case", async () => {
    const user = userEvent.setup();
    render(<CaseList cases={CASES} />);
    await user.type(screen.getByLabelText("search cases"), "nobody-has-this-name");

    expect(screen.getByText("No cases match these filters.")).toBeInTheDocument();
  });

  it("expands and collapses a case's audit trail on click", async () => {
    const user = userEvent.setup();
    render(<CaseList cases={CASES} />);
    const row = screen.getByRole("button", { name: /Arjun Verma/ });

    expect(row).toHaveAttribute("aria-expanded", "false");
    await user.click(row);
    expect(row).toHaveAttribute("aria-expanded", "true");
    expect(within(row.parentElement as HTMLElement).getByText(/"amount": 1000/)).toBeInTheDocument();

    await user.click(row);
    expect(row).toHaveAttribute("aria-expanded", "false");
  });

  it("paginates: shows a Show-more control only once there are more cases than the page size", () => {
    const many = Array.from({ length: 30 }, (_, i) =>
      makeCase({ signal_id: `bulk-${i}`, customer_name: `Bulk Customer ${i}` }),
    );
    render(<CaseList cases={many} />);

    expect(screen.getByText(/Showing 25 of 30/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Show 5 more/ })).toBeInTheDocument();
  });

  it("reveals the rest of the list when Show more is clicked", async () => {
    const user = userEvent.setup();
    const many = Array.from({ length: 30 }, (_, i) =>
      makeCase({ signal_id: `bulk-${i}`, customer_name: `Bulk Customer ${i}` }),
    );
    render(<CaseList cases={many} />);

    await user.click(screen.getByRole("button", { name: /Show 5 more/ }));
    expect(screen.getByText(/Showing 30 of 30/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Show.*more/ })).not.toBeInTheDocument();
  });

  it("resets pagination back to the first page when a filter changes", async () => {
    const user = userEvent.setup();
    const many = Array.from({ length: 30 }, (_, i) =>
      makeCase({
        signal_id: `bulk-${i}`,
        customer_name: `Bulk Customer ${i}`,
        outcome: i === 29 ? "escalated" : "sent",
      }),
    );
    render(<CaseList cases={many} />);

    await user.click(screen.getByRole("button", { name: /Show 5 more/ }));
    await user.click(screen.getByRole("button", { name: /^escalated$/ }));

    // Only one case matches, and pagination didn't stay stuck at a stale
    // "visible" count that would have hidden it.
    expect(screen.getByText(/Showing 1 of 1/)).toBeInTheDocument();
  });
});
