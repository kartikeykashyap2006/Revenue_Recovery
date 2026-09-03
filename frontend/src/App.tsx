import { BrowserRouter, Route, Routes } from "react-router-dom";
import { DashboardProvider } from "./context/DashboardContext";
import { AppShell } from "./layout/AppShell";
import { Overview } from "./pages/Overview";
import { Cases } from "./pages/Cases";
import { Agent } from "./pages/Agent";

export default function App() {
  return (
    <DashboardProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/" element={<Overview />} />
            <Route path="/cases" element={<Cases />} />
            <Route path="/agent" element={<Agent />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </DashboardProvider>
  );
}
