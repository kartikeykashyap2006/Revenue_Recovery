import type { DashboardResponse, RunConfig } from "./types";

/**
 * In dev, Vite proxies /api to the backend (see vite.config.ts), so the app
 * makes same-origin requests and there is no CORS dance to debug. Set
 * VITE_API_BASE to point a built bundle at a backend on another host.
 */
const BASE = import.meta.env.VITE_API_BASE ?? "";

/** Thrown when the backend is unreachable, so the UI can say so precisely. */
export class BackendUnreachable extends Error {
  constructor(cause: unknown) {
    super(
      "Could not reach the backend. Start it with `uvicorn app.main:app --reload` " +
        "from the backend/ folder.",
    );
    this.name = "BackendUnreachable";
    this.cause = cause;
  }
}

// Vite's dev-server proxy (see vite.config.ts) sits in front of the backend,
// so "the backend is down" doesn't always surface as a failed fetch -- the
// proxy itself responds, just with 502/503/504, when it can't reach the
// upstream target. Both cases mean the same thing to the user and deserve
// the same actionable message, not a bare "failed: 502".
const PROXY_UNREACHABLE_STATUSES = new Set([502, 503, 504]);

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, init);
  } catch (cause) {
    throw new BackendUnreachable(cause);
  }
  if (PROXY_UNREACHABLE_STATUSES.has(response.status)) {
    throw new BackendUnreachable(new Error(`proxy returned ${response.status}`));
  }
  if (!response.ok) {
    let detail = "";
    try {
      detail = (await response.json())?.detail ?? "";
    } catch {
      // response body wasn't JSON -- fall through with no extra detail
    }
    throw new Error(`${init?.method ?? "GET"} ${path} failed: ${response.status}${detail ? ` (${detail})` : ""}`);
  }
  return (await response.json()) as T;
}

export function fetchDashboard(): Promise<DashboardResponse> {
  return request<DashboardResponse>("/api/dashboard");
}

export function fetchConfig(): Promise<RunConfig> {
  return request<RunConfig>("/api/config");
}

export function runBatch(params: {
  n: number;
  seed?: number;
  simulateTime?: string;
}): Promise<DashboardResponse> {
  const query = new URLSearchParams({ n: String(params.n) });
  if (params.seed !== undefined) query.set("seed", String(params.seed));
  if (params.simulateTime) query.set("simulate_time", params.simulateTime);
  return request<DashboardResponse>(`/api/run-batch?${query}`, { method: "POST" });
}
