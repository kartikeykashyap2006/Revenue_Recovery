import { useDashboard } from "../context/DashboardContext";
import { CaseList } from "../components/CaseList";

export function Cases() {
  const { ready } = useDashboard();
  return <CaseList cases={ready!.cases} />;
}
