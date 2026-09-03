import { createContext, useCallback, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { fetchConfig, fetchDashboard, runBatch } from "../api";
import type { Dashboard, DashboardResponse, RunConfig } from "../types";

const DEFAULT_SIMULATE_TIME = "2026-08-31T10:00";

interface Ctx {
  data: DashboardResponse | null;
  /** The dashboard payload, only once it's actually non-empty -- pages read
   *  this instead of re-checking `data.empty` everywhere. */
  ready: Dashboard | null;
  config: RunConfig | null;
  error: Error | null;
  busy: boolean;
  size: number;
  setSize: (n: number) => void;
  seed: string;
  setSeed: (s: string) => void;
  simulateTime: string;
  setSimulateTime: (s: string) => void;
  showControls: boolean;
  setShowControls: (fn: boolean | ((v: boolean) => boolean)) => void;
  runNow: () => Promise<void>;
}

const DashboardCtx = createContext<Ctx | null>(null);

export function DashboardProvider({ children }: { children: ReactNode }) {
  const [data, setData] = useState<DashboardResponse | null>(null);
  const [config, setConfig] = useState<RunConfig | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [busy, setBusy] = useState(false);
  const [size, setSize] = useState(25);
  const [seed, setSeed] = useState("");
  const [simulateTime, setSimulateTime] = useState(DEFAULT_SIMULATE_TIME);
  const [showControls, setShowControls] = useState(false);

  const load = useCallback(async () => {
    try {
      setError(null);
      const [dashboard, cfg] = await Promise.all([fetchDashboard(), fetchConfig()]);
      setData(dashboard);
      setConfig(cfg);
    } catch (e) {
      setError(e as Error);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const runNow = useCallback(async () => {
    setBusy(true);
    try {
      setError(null);
      // A batch with the agent enabled makes a real model call per cleared
      // signal, so this can take a few seconds -- callers should disable
      // their trigger on `busy` rather than letting a second run pile on.
      setData(
        await runBatch({
          n: size,
          seed: seed.trim() === "" ? undefined : Number(seed),
          simulateTime: simulateTime || undefined,
        }),
      );
    } catch (e) {
      setError(e as Error);
    } finally {
      setBusy(false);
    }
  }, [size, seed, simulateTime]);

  const ready = data && !data.empty ? data : null;

  return (
    <DashboardCtx.Provider
      value={{
        data,
        ready,
        config,
        error,
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
      }}
    >
      {children}
    </DashboardCtx.Provider>
  );
}

export function useDashboard(): Ctx {
  const ctx = useContext(DashboardCtx);
  if (!ctx) throw new Error("useDashboard must be used within a DashboardProvider");
  return ctx;
}
