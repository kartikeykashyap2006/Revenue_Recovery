import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BackendUnreachable, fetchConfig, fetchDashboard, resetBatch, runBatch } from "./api";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("fetchDashboard", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });
  afterEach(() => vi.unstubAllGlobals());

  it("returns the parsed payload on success", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ empty: true, reason: "no batch yet" }));
    const result = await fetchDashboard();
    expect(result).toEqual({ empty: true, reason: "no batch yet" });
    expect(fetch).toHaveBeenCalledWith("/api/dashboard", undefined);
  });

  it("throws BackendUnreachable when fetch itself rejects (true network failure)", async () => {
    vi.mocked(fetch).mockRejectedValue(new TypeError("Failed to fetch"));
    await expect(fetchDashboard()).rejects.toBeInstanceOf(BackendUnreachable);
  });

  // Regression: Vite's dev proxy responds with 502/503/504 rather than
  // letting fetch() throw when the backend is down, so the old code path
  // (only catching a thrown fetch) surfaced a bare "failed: 502" instead of
  // the actionable "could not reach the backend" message.
  it.each([502, 503, 504])(
    "throws BackendUnreachable when the dev proxy itself responds %i",
    async (status) => {
      vi.mocked(fetch).mockResolvedValue(new Response("Bad Gateway", { status }));
      await expect(fetchDashboard()).rejects.toBeInstanceOf(BackendUnreachable);
    },
  );

  it("does not treat an ordinary 404 as backend-unreachable", async () => {
    vi.mocked(fetch).mockResolvedValue(new Response("{}", { status: 404 }));
    await expect(fetchDashboard()).rejects.not.toBeInstanceOf(BackendUnreachable);
  });

  it("surfaces the backend's own error detail in the thrown message", async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse({ detail: "simulate_time is not a valid ISO datetime: 'garbage'" }, 400),
    );
    await expect(fetchDashboard()).rejects.toThrow(/simulate_time is not a valid ISO datetime/);
  });

  it("still throws a usable error when the error body isn't JSON", async () => {
    vi.mocked(fetch).mockResolvedValue(new Response("plain text 500", { status: 500 }));
    await expect(fetchDashboard()).rejects.toThrow(/failed: 500/);
  });
});

describe("runBatch", () => {
  beforeEach(() => vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ empty: true, reason: "x" }))));
  afterEach(() => vi.unstubAllGlobals());

  it("always sends n, and only sends seed/simulateTime when provided", async () => {
    await runBatch({ n: 25 });
    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe("/api/run-batch?n=25");
    expect(init).toMatchObject({ method: "POST" });
  });

  it("includes seed and simulate_time when given", async () => {
    await runBatch({ n: 80, seed: 7, simulateTime: "2026-08-31T10:00" });
    const [url] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe("/api/run-batch?n=80&seed=7&simulate_time=2026-08-31T10%3A00");
  });
});

describe("resetBatch", () => {
  it("posts to /api/reset", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ empty: true, reason: "cleared" })));
    await resetBatch();
    expect(fetch).toHaveBeenCalledWith("/api/reset", { method: "POST" });
    vi.unstubAllGlobals();
  });
});

describe("fetchConfig", () => {
  it("returns the AI-agent config payload", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ use_ai_recovery_agent: true, llm_provider: "nvidia" })),
    );
    const config = await fetchConfig();
    expect(config).toEqual({ use_ai_recovery_agent: true, llm_provider: "nvidia" });
    vi.unstubAllGlobals();
  });
});
