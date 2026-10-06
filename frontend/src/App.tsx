/*
THESIS: One role-aware operations workspace for a single, reconcilable call model.
OWN-WORLD: Bank operations; synthetic Indian demo records, masked customer IDs.
STORY: See outcomes → find risk → inspect a call → record a governed action.
FIRST VIEWPORT: Navigation, current workspace, shared filters and a concise KPI/data state.
FORM: Navy rail + bright canvas, restrained teal action color, semantic status accents.
API: UI reads the typed dashboard adapter; demo mode uses deterministic synthetic data.
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

const OverviewPage = lazy(() => import("./pages/OverviewPage").then((m) => ({ default: m.OverviewPage })));
const TeamPage = lazy(() => import("./pages/TeamPage").then((m) => ({ default: m.TeamPage })));
const AgentWorkspacePage = lazy(() => import("./pages/AgentWorkspacePage").then((m) => ({ default: m.AgentWorkspacePage })));
const LiveCallsPage = lazy(() => import("./pages/LiveCallsPage").then((m) => ({ default: m.LiveCallsPage })));
const CallLogPage = lazy(() => import("./pages/CallLogPage").then((m) => ({ default: m.CallLogPage })));
const CustomerJourneyPage = lazy(() => import("./pages/CustomerJourneyPage").then((m) => ({ default: m.CustomerJourneyPage })));
const CallbacksPage = lazy(() => import("./pages/CallbacksPage").then((m) => ({ default: m.CallbacksPage })));
const EscalationsPage = lazy(() => import("./pages/EscalationsPage").then((m) => ({ default: m.EscalationsPage })));
const CampaignsPage = lazy(() => import("./pages/CampaignsPage").then((m) => ({ default: m.CampaignsPage })));
const InsightsPage = lazy(() => import("./pages/InsightsPage").then((m) => ({ default: m.InsightsPage })));
const ReportsPage = lazy(() => import("./pages/ReportsPage").then((m) => ({ default: m.ReportsPage })));
const CompliancePage = lazy(() => import("./pages/CompliancePage").then((m) => ({ default: m.CompliancePage })));
const SystemHealthPage = lazy(() => import("./pages/SystemHealthPage").then((m) => ({ default: m.SystemHealthPage })));
const TestConsolePage = lazy(() => import("./pages/TestConsolePage").then((m) => ({ default: m.TestConsolePage })));

function LazyPage({ component: Component }: { component: ComponentType }) {
  return <Suspense fallback={<div className="ops-page-state" role="status">Loading workspace…</div>}><Component /></Suspense>;
}

function Guard({ page }: { page: RouteKey }) {
  const [role] = useRole();
  const location = useLocation();
  if (!ROLE_ACCESS[role].routes.includes(page)) return <Navigate to={ROUTES[ROLE_ACCESS[role].home].path} replace state={{ from: location.pathname }} />;
  return <Outlet />;
}
function RoleHome() { const [role] = useRole(); return <Navigate to={ROUTES[ROLE_ACCESS[role].home].path} replace />; }

export default function App() {
  return <BrowserRouter><RoleProvider><DashboardProvider><Routes><Route element={<AppShell />}>
    <Route path="/" element={<RoleHome />} />
    <Route element={<Guard page="executive" />}><Route path="/executive" element={<LazyPage component={OverviewPage} />} /></Route>
    <Route element={<Guard page="team" />}><Route path="/team" element={<LazyPage component={TeamPage} />} /></Route>
    <Route element={<Guard page="my-work" />}><Route path="/my-work" element={<LazyPage component={AgentWorkspacePage} />} /></Route>
    <Route element={<Guard page="live-calls" />}><Route path="/live-calls" element={<LazyPage component={LiveCallsPage} />} /></Route>
    <Route element={<Guard page="call-log" />}><Route path="/call-log" element={<LazyPage component={CallLogPage} />} /></Route>
    <Route element={<Guard page="customer-journey" />}><Route path="/customer-journey" element={<LazyPage component={CustomerJourneyPage} />} /></Route>
    <Route element={<Guard page="callbacks" />}><Route path="/callbacks" element={<LazyPage component={CallbacksPage} />} /></Route>
    <Route element={<Guard page="escalations" />}><Route path="/escalations" element={<LazyPage component={EscalationsPage} />} /></Route>
    <Route element={<Guard page="campaigns" />}><Route path="/campaigns" element={<LazyPage component={CampaignsPage} />} /></Route>
    <Route element={<Guard page="insights" />}><Route path="/insights" element={<LazyPage component={InsightsPage} />} /></Route>
    <Route element={<Guard page="reports" />}><Route path="/reports" element={<LazyPage component={ReportsPage} />} /></Route>
    <Route element={<Guard page="compliance" />}><Route path="/compliance" element={<LazyPage component={CompliancePage} />} /></Route>
    <Route element={<Guard page="system-health" />}><Route path="/system-health" element={<LazyPage component={SystemHealthPage} />} /></Route>
    <Route element={<Guard page="test-console" />}><Route path="/test-console" element={<LazyPage component={TestConsolePage} />} /></Route>
    <Route path="*" element={<RoleHome />} />
  </Route></Routes></DashboardProvider></RoleProvider></BrowserRouter>;
}
