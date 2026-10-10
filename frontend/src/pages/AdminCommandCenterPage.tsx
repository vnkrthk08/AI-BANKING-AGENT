import { useState } from "react";
import {
  CheckCircle,
  Copy,
  Database,
  Eye,
  Lock,
  MagnifyingGlass,
  ShieldCheck,
  SlidersHorizontal,
  Trash,
  UsersThree,
} from "@phosphor-icons/react";
import { useAuth } from "../auth/AuthContext";
import { useApi } from "../hooks/useApi";
import { apiJson } from "../services/http";
import { fmtRelative, useToast } from "../components/ui";

interface DirectoryUser {
  id: string;
  username: string;
  email: string;
  full_name: string;
  role: string;
  branch: string;
  is_active: boolean;
  demo_password?: string;
  role_description?: string;
  permissions: string[];
  availability?: string;
  agent_profile?: {
    agent_id: string;
    availability: string;
    skills: string[];
    languages: string[];
    active_calls: number;
    handled_today: number;
  } | null;
  recent_actions?: Array<{
    id: string;
    action: string;
    resourceType: string;
    resourceId: string;
    detail: string;
    timestamp?: string;
  }>;
}

interface DirectoryResponse {
  users: DirectoryUser[];
  total_users: number;
  active_users: number;
  roles_present: string[];
}

interface DemoDataStatus {
  is_loaded: boolean;
  customers_count: number;
  campaigns_count: number;
  calls_count: number;
  cases_count: number;
  callbacks_count: number;
  summary: string;
}

const ROLE_THEMES: Record<string, { color: string; bg: string; border: string; label: string }> = {
  SUPER_ADMIN: { color: "#8b5cf6", bg: "rgba(139, 92, 246, 0.12)", border: "#8b5cf6", label: "Super Admin (Platform Exec)" },
  OPS_MANAGER: { color: "#10b981", bg: "rgba(16, 185, 129, 0.12)", border: "#10b981", label: "Operations Manager" },
  SUPERVISOR: { color: "#06b6d4", bg: "rgba(6, 182, 212, 0.12)", border: "#06b6d4", label: "Shift Supervisor" },
  AGENT: { color: "#f59e0b", bg: "rgba(245, 158, 11, 0.12)", border: "#f59e0b", label: "Customer Service Agent" },
  COMPLIANCE_OFFICER: { color: "#f43f5e", bg: "rgba(244, 63, 94, 0.12)", border: "#f43f5e", label: "Compliance & Risk Officer" },
  AUDITOR: { color: "#6366f1", bg: "rgba(99, 102, 241, 0.12)", border: "#6366f1", label: "Independent Auditor" },
  SYSTEM_ADMIN: { color: "#64748b", bg: "rgba(100, 116, 139, 0.12)", border: "#64748b", label: "System Administrator" },
};

const MATRIX_CAPABILITIES = [
  { name: "Executive Overview & Analytics", ops: true, sup: true, agt: false, comp: true, audit: true, sys: false, super: true },
  { name: "AI Voice Studio Calling", ops: true, sup: true, agt: true, comp: false, audit: false, sys: false, super: true },
  { name: "Customer PII & Profile View", ops: true, sup: true, agt: true, comp: true, audit: true, sys: false, super: true },
  { name: "Call Transcripts & Recordings", ops: true, sup: true, agt: true, comp: true, audit: true, sys: false, super: true },
  { name: "Case Resolution & Updates", ops: true, sup: true, agt: true, comp: false, audit: false, sys: false, super: true },
  { name: "Case Reassignment Across Agents", ops: true, sup: true, agt: false, comp: false, audit: false, sys: false, super: true },
  { name: "Campaign Creation & Drafting", ops: true, sup: false, agt: false, comp: false, audit: false, sys: false, super: true },
  { name: "Dual-Control Campaign Approval", ops: false, sup: false, agt: false, comp: true, audit: false, sys: false, super: true },
  { name: "Outbound Campaign Dialing", ops: true, sup: false, agt: false, comp: false, audit: false, sys: false, super: true },
  { name: "TRAI Customer Consent Ledger", ops: false, sup: false, agt: false, comp: true, audit: true, sys: false, super: true },
  { name: "Emergency Dialing Stop", ops: true, sup: true, agt: false, comp: true, audit: false, sys: true, super: true },
  { name: "Resume Dialing Controls", ops: true, sup: false, agt: false, comp: false, audit: false, sys: true, super: true },
  { name: "Regulatory Compliance Audit Logs", ops: true, sup: true, agt: false, comp: true, audit: true, sys: true, super: true },
  { name: "User Account Provisioning", ops: false, sup: false, agt: false, comp: false, audit: false, sys: true, super: true },
  { name: "Live Persona Impersonation Switch", ops: false, sup: false, agt: false, comp: false, audit: false, sys: false, super: true },
];

export function AdminCommandCenterPage() {
  const { user, impersonate } = useAuth();
  const { data, loading, reload } = useApi<DirectoryResponse>("/api/v1/auth/directory");
  const { data: demoStatus, reload: reloadDemoStatus } = useApi<DemoDataStatus>("/api/v1/auth/demo-data/status");
  const toast = useToast();

  const [activeTab, setActiveTab] = useState<"directory" | "feed" | "matrix">("directory");
  const [roleFilter, setRoleFilter] = useState<string>("ALL");
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [switching, setSwitching] = useState<string | null>(null);
  const [seeding, setSeeding] = useState(false);
  const [resetting, setResetting] = useState(false);

  const users = data?.users || [];

  const filteredUsers = users.filter((u) => {
    if (roleFilter !== "ALL" && u.role !== roleFilter) return false;
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      const matchName = u.full_name.toLowerCase().includes(q);
      const matchUsername = u.username.toLowerCase().includes(q);
      const matchBranch = u.branch.toLowerCase().includes(q);
      const matchRole = u.role.toLowerCase().includes(q);
      return matchName || matchUsername || matchBranch || matchRole;
    }
    return true;
  });

  const handleCopyCredentials = (u: DirectoryUser) => {
    const credText = `Username: ${u.username}\nPassword: ${u.demo_password || "Demo-Pass-2026!"}`;
    navigator.clipboard.writeText(credText).then(() => {
      toast.ok(
        "Credentials Copied",
        `Copied login details for ${u.username} (${u.role}) to clipboard`
      );
    });
  };

  const handleSwitchUser = async (targetUsername: string) => {
    try {
      setSwitching(targetUsername);
      toast.info(
        "Switching Perspective",
        `Authenticating session as ${targetUsername}…`
      );
      await impersonate(targetUsername);
      toast.ok(
        "Switched Successfully",
        `Now viewing platform as ${targetUsername}. Use the top banner to return anytime.`
      );
    } catch (err) {
      toast.bad(
        "Switch Failed",
        err instanceof Error ? err.message : "Unable to impersonate user"
      );
    } finally {
      setSwitching(null);
    }
  };

  const handleSeedDemoData = async () => {
    try {
      setSeeding(true);
      toast.info("Populating Demo Data", "Seeding customers, active campaigns, call records, and cases…");
      const res = await apiJson<{ status: string; counts: Record<string, number> }>("/api/v1/auth/demo-data/seed", {
        method: "POST",
      });
      toast.ok(
        "Presentation Data Loaded!",
        `Seeded ${res.counts.customers} customers, ${res.counts.campaigns} campaigns, ${res.counts.calls} calls, and ${res.counts.cases} cases.`
      );
      void reloadDemoStatus();
      void reload();
    } catch (err) {
      toast.bad("Seed Failed", err instanceof Error ? err.message : "Unable to seed demo data");
    } finally {
      setSeeding(false);
    }
  };

  const handleResetDemoData = async () => {
    try {
      setResetting(true);
      toast.info("Clearing Demo Data", "Wiping demo customers, campaigns, call logs, and cases…");
      await apiJson("/api/v1/auth/demo-data/reset", { method: "POST" });
      toast.ok(
        "Demo Data Cleared",
        "Platform fixtures successfully reset to pristine state. Staff accounts preserved."
      );
      void reloadDemoStatus();
      void reload();
    } catch (err) {
      toast.bad("Reset Failed", err instanceof Error ? err.message : "Unable to reset demo data");
    } finally {
      setResetting(false);
    }
  };

  return (
    <div className="admin-page">
      {/* Executive Command Header */}
      <div className="admin-header">
        <div>
          <div className="admin-title-row">
            <h1>Platform Administration & User Directory</h1>
            <span className="presentation-badge">
              <ShieldCheck size={14} weight="fill" /> Presentation Command Center
            </span>
          </div>
          <p className="admin-subtitle">
            Universal operations oversight, multi-role staff personas, live operator activity stream, and seamless one-click presentation switcher.
          </p>
        </div>

        <div className="admin-kpi-bar">
          <div className="admin-kpi-card">
            <span className="kpi-label">Active Personas</span>
            <b className="kpi-val">{data?.total_users || 6}</b>
            <small>Pre-seeded Staff</small>
          </div>
          <div className="admin-kpi-card">
            <span className="kpi-label">Live Roles</span>
            <b className="kpi-val">{data?.roles_present?.length || 6}</b>
            <small>Enforced via RBAC</small>
          </div>
          <div className="admin-kpi-card">
            <span className="kpi-label">Maker-Checker</span>
            <b className="kpi-val ok-text">Enforced</b>
            <small>Dual-Control Active</small>
          </div>
          <div className="admin-kpi-card">
            <span className="kpi-label">PII Isolation</span>
            <b className="kpi-val ok-text">Protected</b>
            <small>Zero-PII IT Boundary</small>
          </div>
        </div>
      </div>

      {/* Presentation Demo Data Controls Bar */}
      <div className="demo-controls-card">
        <div className="demo-controls-left">
          <div className="demo-status-pill-wrap">
            <span className="demo-pill-title">Presentation Data Fixtures:</span>
            <span className={`status-pill ${demoStatus?.is_loaded ? "loaded" : "empty"}`}>
              {demoStatus?.is_loaded ? "● Active Fixtures Loaded" : "○ Pristine / Empty"}
            </span>
          </div>
          <p className="demo-controls-desc">
            {demoStatus?.is_loaded
              ? `Currently loaded: ${demoStatus.summary}. Ready for comprehensive walkthrough.`
              : "No demo fixtures populated. Click 'Populate Demo Data' to load customers, campaigns, calls, and cases."}
          </p>
        </div>

        <div className="demo-controls-actions">
          <button
            className="btn primary demo-seed-btn"
            disabled={seeding}
            onClick={handleSeedDemoData}
          >
            <Database size={16} />
            {seeding ? "Populating Fixtures…" : "Populate Demo Data"}
          </button>
          <button
            className="btn secondary demo-reset-btn"
            disabled={resetting}
            onClick={handleResetDemoData}
          >
            <Trash size={16} />
            {resetting ? "Cleaning Data…" : "Clear / Reset Demo Data"}
          </button>
        </div>
      </div>

      {/* Navigation Sub-Tabs */}
      <div className="admin-subtabs">
        <button
          className={`subtab-btn ${activeTab === "directory" ? "active" : ""}`}
          onClick={() => setActiveTab("directory")}
        >
          <UsersThree size={16} />
          <span>Staff Directory & Personas</span>
          <span className="pill-count">{users.length}</span>
        </button>

        <button
          className={`subtab-btn ${activeTab === "feed" ? "active" : ""}`}
          onClick={() => setActiveTab("feed")}
        >
          <SlidersHorizontal size={16} />
          <span>Live Operator Activity Feed</span>
        </button>

        <button
          className={`subtab-btn ${activeTab === "matrix" ? "active" : ""}`}
          onClick={() => setActiveTab("matrix")}
        >
          <ShieldCheck size={16} />
          <span>Banking RBAC Capability Matrix</span>
        </button>
      </div>

      {/* TAB 1: Staff Directory & Personas */}
      {activeTab === "directory" && (
        <div className="admin-tab-content">
          <div className="directory-toolbar">
            <div className="search-wrap">
              <MagnifyingGlass size={16} className="search-icon" />
              <input
                type="text"
                className="input search-input"
                placeholder="Search staff by name, username, branch, or role…"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />
            </div>

            <div className="filter-chips">
              {["ALL", "SUPER_ADMIN", "OPS_MANAGER", "SUPERVISOR", "AGENT", "COMPLIANCE_OFFICER", "AUDITOR"].map(
                (r) => (
                  <button
                    key={r}
                    className={`filter-chip ${roleFilter === r ? "active" : ""}`}
                    onClick={() => setRoleFilter(r)}
                  >
                    {r === "ALL" ? "All Roles" : r.replace("_", " ")}
                  </button>
                )
              )}
            </div>
          </div>

          {loading ? (
            <div className="loading-state">Loading staff personas…</div>
          ) : (
            <div className="user-cards-grid">
              {filteredUsers.map((u) => {
                const theme = ROLE_THEMES[u.role] || {
                  color: "#3b82f6",
                  bg: "rgba(59, 130, 246, 0.12)",
                  border: "#3b82f6",
                  label: u.role,
                };
                const isCurrentUser = user?.username === u.username;
                const isAgent = u.role === "AGENT" && Boolean(u.agent_profile);

                return (
                  <div key={u.id} className="user-persona-card" style={{ borderTop: `4px solid ${theme.border}` }}>
                    <div className="card-top">
                      <div className="avatar-wrap">
                        <span className="user-avatar" style={{ background: theme.bg, color: theme.color }}>
                          {u.full_name
                            .split(" ")
                            .map((p) => p[0])
                            .join("")
                            .slice(0, 2)
                            .toUpperCase()}
                        </span>
                        <span className={`status-dot ${u.availability === "AVAILABLE" ? "green" : "blue"}`} />
                      </div>

                      <div className="user-info">
                        <div className="name-row">
                          <h3 className="user-name">{u.full_name}</h3>
                          {isCurrentUser && <span className="you-pill">You</span>}
                        </div>
                        <span className="user-username">@{u.username}</span>
                        <div className="branch-meta">
                          <span>{u.branch}</span> &bull; <span>{u.email}</span>
                        </div>
                      </div>

                      <div className="role-badge-wrap">
                        <span
                          className="role-badge"
                          style={{ color: theme.color, backgroundColor: theme.bg, borderColor: theme.border }}
                        >
                          {theme.label}
                        </span>
                      </div>
                    </div>

                    <p className="role-desc">
                      {u.role_description || "Operational bank staff handling specialized contact center workflows."}
                    </p>

                    {/* Agent profile metrics if linked */}
                    {isAgent && u.agent_profile && (
                      <div className="agent-chips-box">
                        <div className="skills-line">
                          <strong>Skills:</strong>
                          {u.agent_profile.skills.map((s) => (
                            <span key={s} className="skill-pill">
                              {s.replace("_", " ")}
                            </span>
                          ))}
                        </div>
                        <div className="skills-line">
                          <strong>Languages:</strong>
                          {u.agent_profile.languages.map((l) => (
                            <span key={l} className="lang-pill">
                              {l}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Demo Credentials Box */}
                    <div className="credentials-box">
                      <div className="cred-row">
                        <div className="cred-field">
                          <span className="cred-lbl">Login Username</span>
                          <code className="cred-val">{u.username}</code>
                        </div>
                        <div className="cred-field">
                          <span className="cred-lbl">Demo Password</span>
                          <code className="cred-val">{u.demo_password || "Demo-Pass-2026!"}</code>
                        </div>
                        <button
                          className="btn sm ghost copy-btn"
                          title="Copy Username and Password"
                          onClick={() => handleCopyCredentials(u)}
                        >
                          <Copy size={14} /> Copy
                        </button>
                      </div>
                    </div>

                    {/* Bottom Action Footer */}
                    <div className="card-footer">
                      <div className="footer-status">
                        <span className="status-label">Shift Status:</span>
                        <span className="status-text">{u.availability || "ACTIVE"}</span>
                      </div>

                      {isCurrentUser ? (
                        <button className="btn sm secondary current-btn" disabled>
                          <CheckCircle size={14} weight="fill" /> Active Session
                        </button>
                      ) : (
                        <button
                          className="btn sm primary switch-btn"
                          disabled={switching === u.username}
                          onClick={() => handleSwitchUser(u.username)}
                        >
                          <Eye size={14} />
                          {switching === u.username ? "Switching…" : `Switch to ${u.username}`}
                        </button>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* TAB 2: Live Activity Feed */}
      {activeTab === "feed" && (
        <div className="admin-tab-content">
          <div className="feed-card">
            <div className="feed-header">
              <div>
                <h2>Real-Time Operator Activity Stream</h2>
                <p>Audited actions and operational decisions taken by bank staff across active workflows.</p>
              </div>
              <button className="btn sm secondary" onClick={() => void reload()}>
                Refresh Stream
              </button>
            </div>

            <div className="activity-timeline">
              {users.flatMap((u) => u.recent_actions || []).length === 0 ? (
                <div className="empty-state">No recent activity logged yet.</div>
              ) : (
                users
                  .flatMap((u) => (u.recent_actions || []).map((a) => ({ ...a, user: u })))
                  .sort((a, b) => (b.timestamp || "").localeCompare(a.timestamp || ""))
                  .map((act, idx) => {
                    const theme = ROLE_THEMES[act.user.role] || { color: "#3b82f6", bg: "rgba(59, 130, 246, 0.12)" };
                    return (
                      <div key={act.id || idx} className="activity-item">
                        <div className="act-marker" style={{ borderColor: theme.color, backgroundColor: theme.bg }} />
                        <div className="act-body">
                          <div className="act-top">
                            <span className="act-actor">
                              <strong>{act.user.full_name}</strong> (@{act.user.username})
                            </span>
                            <span
                              className="act-role-pill"
                              style={{ color: theme.color, backgroundColor: theme.bg }}
                            >
                              {act.user.role}
                            </span>
                            <span className="act-action-badge">{act.action}</span>
                            <span className="act-time">{fmtRelative(act.timestamp)}</span>
                          </div>
                          <p className="act-detail">{act.detail}</p>
                          <div className="act-resource">
                            <span>Resource: <code>{act.resourceType}</code> / <code>{act.resourceId}</code></span>
                          </div>
                        </div>
                      </div>
                    );
                  })
              )}
            </div>
          </div>
        </div>
      )}

      {/* TAB 3: Governance RBAC Matrix */}
      {activeTab === "matrix" && (
        <div className="admin-tab-content">
          <div className="matrix-card">
            <div className="matrix-header">
              <div>
                <h2>Banking RBAC Capability & Separation-of-Duties Matrix</h2>
                <p>
                  Formal authority boundaries enforced at the FastAPI API layer. Ensures zero unauthorized actions across banking operations.
                </p>
              </div>
            </div>

            <div className="matrix-table-wrap">
              <table className="matrix-table">
                <thead>
                  <tr>
                    <th style={{ width: "30%" }}>Platform Capability</th>
                    <th>SUPER_ADMIN</th>
                    <th>OPS_MANAGER</th>
                    <th>SUPERVISOR</th>
                    <th>AGENT</th>
                    <th>COMPLIANCE</th>
                    <th>AUDITOR</th>
                    <th>SYSTEM_ADMIN</th>
                  </tr>
                </thead>
                <tbody>
                  {MATRIX_CAPABILITIES.map((cap) => (
                    <tr key={cap.name}>
                      <td className="cap-name">
                        <b>{cap.name}</b>
                      </td>
                      <td className="cap-cell">{cap.super ? <CheckCircle size={18} className="icon-ok" weight="fill" /> : <Lock size={16} className="icon-lock" />}</td>
                      <td className="cap-cell">{cap.ops ? <CheckCircle size={18} className="icon-ok" weight="fill" /> : <Lock size={16} className="icon-lock" />}</td>
                      <td className="cap-cell">{cap.sup ? <CheckCircle size={18} className="icon-ok" weight="fill" /> : <Lock size={16} className="icon-lock" />}</td>
                      <td className="cap-cell">{cap.agt ? <CheckCircle size={18} className="icon-ok" weight="fill" /> : <Lock size={16} className="icon-lock" />}</td>
                      <td className="cap-cell">{cap.comp ? <CheckCircle size={18} className="icon-ok" weight="fill" /> : <Lock size={16} className="icon-lock" />}</td>
                      <td className="cap-cell">{cap.audit ? <CheckCircle size={18} className="icon-ok" weight="fill" /> : <Lock size={16} className="icon-lock" />}</td>
                      <td className="cap-cell">{cap.sys ? <CheckCircle size={18} className="icon-ok" weight="fill" /> : <Lock size={16} className="icon-lock" />}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="matrix-callout">
              <div className="callout-block">
                <h4>1. Dual-Control "Maker-Checker" Rule</h4>
                <p>
                  Operations Managers can draft outbound dial campaigns, but campaigns remain in <code>PENDING_APPROVAL</code> until a Compliance Officer formally executes <code>campaign:approve</code>.
                </p>
              </div>
              <div className="callout-block">
                <h4>2. Zero-PII IT Boundary</h4>
                <p>
                  System Administrators manage technical infrastructure and user credentials, but are programmatically barred from viewing customer phone numbers, cases, or conversation audio.
                </p>
              </div>
              <div className="callout-block">
                <h4>3. Read-Only Independent Audit</h4>
                <p>
                  Internal and external auditors possess cryptographic read-only privileges across consent ledgers and transcripts, preventing tampering with historical bank records.
                </p>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
