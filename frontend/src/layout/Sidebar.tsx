import { NavLink } from "react-router-dom";
import { IconAgent, IconCases, IconOverview } from "./icons";

const NAV = [
  { to: "/", label: "Overview", icon: IconOverview, end: true },
  { to: "/cases", label: "Cases", icon: IconCases, end: false },
  { to: "/agent", label: "Agent", icon: IconAgent, end: false },
];

export function Sidebar() {
  return (
    <aside className="sidebar">
      <div className="brand">
        <img src="/favicon.svg" alt="" className="brand-mark" />
        <div className="brand-text">
          <span className="brand-name">Recoup</span>
          <span className="brand-sub">AI Revenue Recovery</span>
        </div>
      </div>

      <nav className="nav" aria-label="Primary">
        {NAV.map(({ to, label, icon: Icon, end }) => (
          <NavLink key={to} to={to} end={end} className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}>
            <Icon className="nav-icon" />
            {label}
          </NavLink>
        ))}
      </nav>

      <div className="sidebar-foot">
        <p>Razorpay Buildathon</p>
        <p className="dim">Track 03 · Revenue Recovery</p>
      </div>
    </aside>
  );
}
