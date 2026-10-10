/*
THESIS: Unified 7 Operational Hubs for institutional banking AI operations.
OWN-WORLD: Bank operations; synthetic Indian demo records, masked customer IDs.
HUBS:
1. Overview (/executive, /)
2. AI Voice Studio (/test-console, /voice)
3. Calls Hub (/calls)
4. Campaigns Hub (/campaigns)
5. Work Queue (/work)
6. Team Roster (/team)
7. Governance & System Health (/governance)
*/
import { lazy, Suspense } from "react";
import type { ComponentType } from "react";
import { BrowserRouter, Navigate, Outlet, Route, Routes, useLocation } from "react-router-dom";
import { ROLE_ACCESS, ROUTES, type RouteKey } from "./config/permissions";
import { AppShell } from "./components/AppShell";
import { DashboardProvider } from "./hooks/DashboardContext";
import { useRole } from "./hooks/useRole";
import { RoleProvider } from "./hooks/useRole";
import "./dashboard.css";

// 7 Unified Operational Hubs
const OverviewPage = lazy(() => import("./pages/OverviewPage").then((m) => ({ default: m.OverviewPage })));
const TestConsolePage = lazy(() => import("./pages/TestConsolePage").then((m) => ({ default: m.TestConsolePage })));
const CallsHubPage = lazy(() => import("./pages/CallsHubPage").then((m) => ({ default: m.CallsHubPage })));
const CampaignsPage = lazy(() => import("./pages/CampaignsPage").then((m) => ({ default: m.CampaignsPage })));
const WorkQueuePage = lazy(() => import("./pages/WorkQueuePage").then((m) => ({ default: m.WorkQueuePage })));
const TeamPage = lazy(() => import("./pages/TeamPage").then((m) => ({ default: m.TeamPage })));
const GovernanceHubPage = lazy(() => import("./pages/GovernanceHubPage").then((m) => ({ default: m.GovernanceHubPage })));

function LazyPage({ component: Component }: { component: ComponentType }) {
  return (
    <Suspense fallback={<div className="ops-page-state" role="status">Loading workspace…</div>}>
      <Component />
    </Suspense>
  );
}

function Guard({ page }: { page: RouteKey }) {
  const [role] = useRole();
  const location = useLocation();
  if (!ROLE_ACCESS[role].routes.includes(page)) {
    return <Navigate to={ROUTES[ROLE_ACCESS[role].home].path} replace state={{ from: location.pathname }} />;
  }
  return <Outlet />;
}

function RoleHome() {
  const [role] = useRole();
  return <Navigate to={ROUTES[ROLE_ACCESS[role].home].path} replace />;
}

export default function App() {
  return (
    <BrowserRouter>
      <RoleProvider>
        <DashboardProvider>
          <Routes>
            <Route element={<AppShell />}>
              <Route path="/" element={<RoleHome />} />

              {/* 7 CONSOLIDATED HUBS */}
              <Route element={<Guard page="executive" />}>
                <Route path="/executive" element={<LazyPage component={OverviewPage} />} />
              </Route>
              <Route element={<Guard page="test-console" />}>
                <Route path="/test-console" element={<LazyPage component={TestConsolePage} />} />
                <Route path="/voice" element={<Navigate to="/test-console" replace />} />
              </Route>
              <Route element={<Guard page="calls" />}>
                <Route path="/calls" element={<LazyPage component={CallsHubPage} />} />
              </Route>
              <Route element={<Guard page="campaigns" />}>
                <Route path="/campaigns" element={<LazyPage component={CampaignsPage} />} />
              </Route>
              <Route element={<Guard page="work" />}>
                <Route path="/work" element={<LazyPage component={WorkQueuePage} />} />
              </Route>
              <Route element={<Guard page="team" />}>
                <Route path="/team" element={<LazyPage component={TeamPage} />} />
              </Route>
              <Route element={<Guard page="governance" />}>
                <Route path="/governance" element={<LazyPage component={GovernanceHubPage} />} />
              </Route>

              {/* BACKWARDS-COMPATIBLE LEGACY ROUTES & REDIRECTS */}
              <Route path="/live-calls" element={<Navigate to="/calls" replace />} />
              <Route path="/call-log" element={<Navigate to="/calls" replace />} />
              <Route path="/customer-journey" element={<Navigate to="/calls" replace />} />
              <Route path="/escalations" element={<Navigate to="/work" replace />} />
              <Route path="/callbacks" element={<Navigate to="/work" replace />} />
              <Route path="/my-work" element={<Navigate to="/work" replace />} />
              <Route path="/compliance" element={<Navigate to="/governance" replace />} />
              <Route path="/system-health" element={<Navigate to="/governance" replace />} />
              <Route path="/reports" element={<Navigate to="/governance" replace />} />
              <Route path="/insights" element={<Navigate to="/governance" replace />} />

              <Route path="*" element={<RoleHome />} />
            </Route>
          </Routes>
        </DashboardProvider>
      </RoleProvider>
    </BrowserRouter>
  );
}
