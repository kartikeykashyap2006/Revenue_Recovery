import { Outlet, useLocation } from "react-router-dom";
import { BackendUnreachable } from "../api";
import { useDashboard } from "../context/DashboardContext";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";

const PAGE_META: Record<string, { title: string; subtitle?: string }> = {
  "/": { title: "Overview" },
  "/cases": {
    title: "Cases",
    subtitle: "Search, filter, and open the complete audit trail for any case in the latest batch.",
  },
  "/agent": {
    title: "Agent",
    subtitle: "What the AI recovery-decision agent actually did this run -- not what it's capable of.",
  },
};

export function AppShell() {
  const location = useLocation();
  const meta = PAGE_META[location.pathname] ?? { title: "Recoup" };
  const { data, error, ready } = useDashboard();

  return (
    <div className="shell">
      <Sidebar />
      <div className="main">
        <TopBar title={meta.title} subtitle={meta.subtitle} />
        <div className="content">
          {error && (
            <div className="card state error">
              <strong>{error.message}</strong>
              {error instanceof BackendUnreachable && (
                <p className="note">
                  From the project root: <code>cd backend &amp;&amp; uvicorn app.main:app --reload</code>
                </p>
              )}
            </div>
          )}
          {!data && !error && <div className="state">Loading…</div>}
          {data?.empty && (
            <div className="card state">
              <strong>Nothing to show yet.</strong>
              <p className="note">{data.reason} — press "Run batch" above, or run a batch from the CLI.</p>
            </div>
          )}
          {ready && <Outlet />}
        </div>
      </div>
    </div>
  );
}
