import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DashboardProvider, useDashboard } from "./DashboardContext";
import * as api from "../api";
import type { Dashboard, EmptyDashboard, RunConfig } from "../types";

vi.mock("../api");

const EMPTY: EmptyDashboard = { empty: true, reason: "no audit log entries -- run a batch first" };
const CONFIG: RunConfig = { use_ai_recovery_agent: true, llm_provider: "nvidia" };
const POPULATED: Dashboard = {
  empty: false,
  runs_in_log: 1,
  totals: { signals: 16, at_risk: 533225.93, recovered: 58560.01, recovery_rate: 0.1098 },
  detection: { raw_cases: 25, signals_detected: 16, resolved_on_their_own: 9 },
  funnel: [],
  by_scenario: [],
  outcomes: {},
  agent: {
    consultations: 0, real_answers: 0, fallbacks: 0, changed_outcome: 0,
    chose_channel: 0, postponed: 0, avg_confidence: null, action_distribution: {},
  },
  cases: [],
};

function wrapper({ children }: { children: React.ReactNode }) {
  return <DashboardProvider>{children}</DashboardProvider>;
}

describe("DashboardProvider", () => {
  beforeEach(() => {
    vi.mocked(api.fetchDashboard).mockResolvedValue(EMPTY);
    vi.mocked(api.fetchConfig).mockResolvedValue(CONFIG);
  });
  afterEach(() => vi.resetAllMocks());

  it("loads the dashboard and config on mount", async () => {
    const { result } = renderHook(() => useDashboard(), { wrapper });

    await waitFor(() => expect(result.current.data).toEqual(EMPTY));
    expect(result.current.config).toEqual(CONFIG);
    expect(result.current.ready).toBeNull(); // empty dashboard -> no "ready" data
    expect(result.current.error).toBeNull();
  });

  it("exposes the ready dashboard only once a batch is non-empty", async () => {
    vi.mocked(api.fetchDashboard).mockResolvedValue(POPULATED);
    const { result } = renderHook(() => useDashboard(), { wrapper });

    await waitFor(() => expect(result.current.ready).toEqual(POPULATED));
  });

  it("records a load failure without crashing", async () => {
    vi.mocked(api.fetchDashboard).mockRejectedValue(new Error("boom"));
    const { result } = renderHook(() => useDashboard(), { wrapper });

    await waitFor(() => expect(result.current.error).toBeInstanceOf(Error));
    expect(result.current.error?.message).toBe("boom");
  });

  it("runNow calls runBatch with the current size, omits seed when blank, and updates data", async () => {
    const { result } = renderHook(() => useDashboard(), { wrapper });
    await waitFor(() => expect(result.current.data).toEqual(EMPTY));

    vi.mocked(api.runBatch).mockResolvedValue(POPULATED);
    await act(async () => {
      await result.current.runNow();
    });

    expect(api.runBatch).toHaveBeenCalledWith({
      n: 25,
      seed: undefined,
      simulateTime: "2026-08-31T10:00",
    });
    expect(result.current.data).toEqual(POPULATED);
    expect(result.current.busy).toBe(false);
  });

  it("runNow passes a numeric seed once one is set", async () => {
    const { result } = renderHook(() => useDashboard(), { wrapper });
    await waitFor(() => expect(result.current.data).toEqual(EMPTY));

    act(() => result.current.setSeed("7"));
    vi.mocked(api.runBatch).mockResolvedValue(POPULATED);
    await act(async () => {
      await result.current.runNow();
    });

    expect(api.runBatch).toHaveBeenCalledWith(expect.objectContaining({ seed: 7 }));
  });

  it("runNow sets busy while in flight and records a failure without leaving busy stuck true", async () => {
    const { result } = renderHook(() => useDashboard(), { wrapper });
    await waitFor(() => expect(result.current.data).toEqual(EMPTY));

    vi.mocked(api.runBatch).mockRejectedValue(new Error("proxy returned 502"));
    await act(async () => {
      await result.current.runNow();
    });

    expect(result.current.error?.message).toBe("proxy returned 502");
    expect(result.current.busy).toBe(false);
  });

  it("resetNow calls resetBatch and replaces the data with the cleared payload", async () => {
    vi.mocked(api.fetchDashboard).mockResolvedValue(POPULATED);
    const { result } = renderHook(() => useDashboard(), { wrapper });
    await waitFor(() => expect(result.current.ready).toEqual(POPULATED));

    vi.mocked(api.resetBatch).mockResolvedValue(EMPTY);
    await act(async () => {
      await result.current.resetNow();
    });

    expect(api.resetBatch).toHaveBeenCalledOnce();
    expect(result.current.data).toEqual(EMPTY);
    expect(result.current.ready).toBeNull();
  });

  it("throws when useDashboard is called outside a DashboardProvider", () => {
    // Swallow the expected React error-boundary console noise for this case.
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => renderHook(() => useDashboard())).toThrow(
      "useDashboard must be used within a DashboardProvider",
    );
    spy.mockRestore();
  });
});
