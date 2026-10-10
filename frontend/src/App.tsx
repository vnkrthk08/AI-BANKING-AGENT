import React, { lazy, Suspense } from "react";
import type { ComponentType } from "react";
import { BrowserRouter, Navigate, Outlet, Route, Routes } from "react-router-dom";
import { allowedHubs, homePath, type HubKey } from "./config/hubs";
import { AppShell } from "./components/AppShell";
import { DashboardProvider } from "./hooks/DashboardContext";
import { AuthProvider, useAuth } from "./auth/AuthContext";
import { LoginPage } from "./auth/LoginPage";
import { Loading } from "./components/ui";
import "./styles/ds.css";

const OverviewPage = lazy(() => import("./pages/OverviewPage").then((m) => ({ default: m.OverviewPage })));
const VoiceStudio = lazy(() => import("./pages/TestConsolePage").then((m) => ({ default: m.TestConsolePage })));
const CallsHubPage = lazy(() => import("./pages/CallsHubPage").then((m) => ({ default: m.CallsHubPage })));
const CampaignsPage = lazy(() => import("./pages/CampaignsPage").then((m) => ({ default: m.CampaignsPage })));
const WorkQueuePage = lazy(() => import("./pages/WorkQueuePage").then((m) => ({ default: m.WorkQueuePage })));
const TeamPage = lazy(() => import("./pages/TeamPage").then((m) => ({ default: m.TeamPage })));
const GovernanceHubPage = lazy(() => import("./pages/GovernanceHubPage").then((m) => ({ default: m.GovernanceHubPage })));

function Page({ component: C }: { component: ComponentType }) {
  return <Suspense fallback={<Loading />}><C /></Suspense>;
}
function Guard({ page }: { page: HubKey }) {
  const { user } = useAuth();
  if (!allowedHubs(user?.permissions).includes(page)) return <Navigate to={homePath(user?.permissions)} replace />;
  return <Outlet />;
}
function Home() {
  const { user } = useAuth();
  return <Navigate to={homePath(user?.permissions)} replace />;
}
function Gate({ children }: { children: React.ReactNode }) {
  const { user, checking, unreachable, retry } = useAuth();
  if (checking) return <div className="boot" role="status">Checking your session…</div>;
  if (unreachable && !user) return (
    <div className="boot" role="alert"><div style={{ textAlign: "center" }}><h1 style={{ fontSize: 18, color: "var(--text)" }}>Cannot reach the AVA backend</h1>
      <p>Your session may still be valid. Check the API server or network, then retry.</p><button className="btn primary" onClick={retry}>Retry</button></div></div>
  );
  if (!user) return <LoginPage />;
  return <DashboardProvider>{children}</DashboardProvider>;
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Gate>
          <Routes>
            <Route element={<AppShell />}>
              <Route path="/" element={<Home />} />
              <Route element={<Guard page="executive" />}><Route path="/executive" element={<Page component={OverviewPage} />} /></Route>
              <Route element={<Guard page="test-console" />}>
                <Route path="/test-console" element={<Page component={VoiceStudio} />} />
                <Route path="/voice" element={<Navigate to="/test-console" replace />} />
              </Route>
              <Route element={<Guard page="calls" />}><Route path="/calls" element={<Page component={CallsHubPage} />} /></Route>
              <Route element={<Guard page="campaigns" />}><Route path="/campaigns" element={<Page component={CampaignsPage} />} /></Route>
              <Route element={<Guard page="work" />}><Route path="/work" element={<Page component={WorkQueuePage} />} /></Route>
              <Route element={<Guard page="team" />}><Route path="/team" element={<Page component={TeamPage} />} /></Route>
              <Route element={<Guard page="governance" />}><Route path="/governance" element={<Page component={GovernanceHubPage} />} /></Route>
              <Route path="/live-calls" element={<Navigate to="/calls" replace />} />
              <Route path="/call-log" element={<Navigate to="/calls" replace />} />
              <Route path="/customer-journey" element={<Navigate to="/calls?tab=customers" replace />} />
              <Route path="/escalations" element={<Navigate to="/work" replace />} />
              <Route path="/callbacks" element={<Navigate to="/work?tab=callbacks" replace />} />
              <Route path="/my-work" element={<Navigate to="/work" replace />} />
              <Route path="/compliance" element={<Navigate to="/governance?tab=compliance" replace />} />
              <Route path="/system-health" element={<Navigate to="/governance" replace />} />
              <Route path="/reports" element={<Navigate to="/calls" replace />} />
              <Route path="/insights" element={<Navigate to="/executive" replace />} />
              <Route path="*" element={<Home />} />
            </Route>
          </Routes>
        </Gate>
      </AuthProvider>
    </BrowserRouter>
  );
}
