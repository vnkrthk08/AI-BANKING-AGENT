import { useState } from "react";
import {
  CheckCircle,
  Copy,
  Database,
  Eye,
  Lock,
  MagnifyingGlass,
  Plus,
  ShieldCheck,
  SlidersHorizontal,
  Trash,
  UsersThree,
  X,
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

  // User Creation Modal State
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [createBusy, setCreateBusy] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [createForm, setCreateForm] = useState({
    username: "",
    full_name: "",
    email: "",
    password: "Kural-Pass-2026!",
    role: "AGENT",
    branch: "Mumbai Metro",
    phone: "",
  });

  // User Deletion Confirmation State
  const [deleteTarget, setDeleteTarget] = useState<DirectoryUser | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);

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

  const handleCreateUserSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setCreateBusy(true);
    setCreateError(null);
    try {
      const payload = {
        username: createForm.username.trim(),
        full_name: createForm.full_name.trim(),
        email: createForm.email.trim(),
        password: createForm.password,
        role: createForm.role,
        branch: createForm.branch.trim() || "Head Office",
        phone: createForm.phone.trim() || undefined,
      };
      await apiJson("/api/v1/auth/users", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      toast.ok(
        "User Created Successfully",
        `Created @${payload.username} (${payload.role}) in ${payload.branch}`
      );
      setCreateModalOpen(false);
      setCreateForm({
        username: "",
        full_name: "",
        email: "",
        password: "Kural-Pass-2026!",
        role: "AGENT",
        branch: "Mumbai Metro",
        phone: "",
      });
      await reload();
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : "Failed to create user account");
    } finally {
      setCreateBusy(false);
    }
  };

  const handleDeleteUserConfirm = async () => {
    if (!deleteTarget) return;
    setDeleteBusy(true);
    try {
      await apiJson(`/api/v1/auth/users/${deleteTarget.id}`, {
        method: "DELETE",
      });
      toast.ok(
        "User Deleted",
        `User account @${deleteTarget.username} (${deleteTarget.full_name}) was permanently deleted.`
      );
      setDeleteTarget(null);
      await reload();
    } catch (err) {
      toast.bad("Delete Failed", err instanceof Error ? err.message : "Unable to delete user");
    } finally {
      setDeleteBusy(false);
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

            <button
              className="btn primary create-account-btn"
              onClick={() => {
                setCreateError(null);
                setCreateModalOpen(true);
              }}
              style={{ display: "inline-flex", alignItems: "center", gap: 6, marginLeft: "auto", flexShrink: 0 }}
            >
              <Plus size={15} weight="bold" />
              <span>Create Account</span>
            </button>
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

                      <div className="card-actions-group" style={{ display: "flex", gap: 6, alignItems: "center" }}>
                        {!isCurrentUser && u.username.toLowerCase() !== "admin" && (
                          <button
                            className="btn sm danger delete-user-btn"
                            title={`Delete account @${u.username}`}
                            onClick={() => setDeleteTarget(u)}
                            style={{ padding: "0 8px", color: "var(--bad)" }}
                          >
                            <Trash size={14} />
                          </button>
                        )}
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

      {/* Modal: Create New User Account */}
      {createModalOpen && (
        <div className="modal-wrap" role="dialog" aria-modal="true" aria-labelledby="create-modal-title">
          <div className="modal create-user-modal" style={{ width: "min(560px, 100%)", maxHeight: "90vh", display: "flex", flexDirection: "column" }}>
            <div className="modal-head" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "18px 24px", borderBottom: "1px solid var(--line)" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <span style={{ width: 32, height: 32, borderRadius: 8, background: "var(--brand-soft)", color: "var(--brand-2)", display: "grid", placeItems: "center" }}>
                  <Plus size={18} weight="bold" />
                </span>
                <div>
                  <h2 id="create-modal-title" style={{ margin: 0, fontSize: 17, fontWeight: 700 }}>Provision Staff Account</h2>
                  <small style={{ color: "var(--text-3)", fontSize: 12 }}>Create a new banking operations operator with RBAC role</small>
                </div>
              </div>
              <button
                className="icon-btn"
                aria-label="Close modal"
                onClick={() => setCreateModalOpen(false)}
              >
                <X size={18} />
              </button>
            </div>

            <form onSubmit={handleCreateUserSubmit} style={{ display: "flex", flexDirection: "column", flex: 1, overflow: "hidden", margin: 0 }}>
              <div className="modal-body" style={{ padding: "20px 24px", overflowY: "auto", display: "grid", gap: 14 }}>
                {createError && (
                  <div className="alert-bad" style={{ padding: "10px 14px", borderRadius: 8, background: "var(--bad-soft)", color: "var(--bad)", fontSize: 13, border: "1px solid var(--bad)" }}>
                    {createError}
                  </div>
                )}

                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                  <div className="field" style={{ margin: 0 }}>
                    <label>Username *</label>
                    <input
                      type="text"
                      className="input"
                      placeholder="e.g. agent2 or ops_lead"
                      required
                      value={createForm.username}
                      onChange={(e) => setCreateForm({ ...createForm, username: e.target.value })}
                    />
                    <small>Lowercase alphanumeric, 3–64 chars</small>
                  </div>

                  <div className="field" style={{ margin: 0 }}>
                    <label>Full Name *</label>
                    <input
                      type="text"
                      className="input"
                      placeholder="e.g. Rajesh Sharma"
                      required
                      value={createForm.full_name}
                      onChange={(e) => setCreateForm({ ...createForm, full_name: e.target.value })}
                    />
                    <small>Official staff legal name</small>
                  </div>
                </div>

                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                  <div className="field" style={{ margin: 0 }}>
                    <label>Corporate Email *</label>
                    <input
                      type="email"
                      className="input"
                      placeholder="staff@kural.bank"
                      required
                      value={createForm.email}
                      onChange={(e) => setCreateForm({ ...createForm, email: e.target.value })}
                    />
                  </div>

                  <div className="field" style={{ margin: 0 }}>
                    <label>Banking Role *</label>
                    <select
                      className="select"
                      value={createForm.role}
                      onChange={(e) => setCreateForm({ ...createForm, role: e.target.value })}
                    >
                      <option value="AGENT">AGENT (Customer Representative)</option>
                      <option value="SUPERVISOR">SUPERVISOR (Shift Lead & QA)</option>
                      <option value="OPS_MANAGER">OPS_MANAGER (Campaign Operations)</option>
                      <option value="COMPLIANCE_OFFICER">COMPLIANCE_OFFICER (Maker-Checker)</option>
                      <option value="AUDITOR">AUDITOR (Read-Only Audit)</option>
                      <option value="SYSTEM_ADMIN">SYSTEM_ADMIN (Zero-PII Admin)</option>
                      <option value="SUPER_ADMIN">SUPER_ADMIN (Platform Executive)</option>
                    </select>
                  </div>
                </div>

                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                  <div className="field" style={{ margin: 0 }}>
                    <label>Branch / Office</label>
                    <input
                      type="text"
                      className="input"
                      placeholder="e.g. Mumbai Metro"
                      value={createForm.branch}
                      onChange={(e) => setCreateForm({ ...createForm, branch: e.target.value })}
                    />
                  </div>

                  <div className="field" style={{ margin: 0 }}>
                    <label>Contact Phone (Optional)</label>
                    <input
                      type="text"
                      className="input"
                      placeholder="+91 98765 43210"
                      value={createForm.phone}
                      onChange={(e) => setCreateForm({ ...createForm, phone: e.target.value })}
                    />
                  </div>
                </div>

                <div className="field" style={{ margin: 0 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <label>Account Password *</label>
                    <button
                      type="button"
                      className="btn sm ghost"
                      style={{ fontSize: 11, padding: "0 6px" }}
                      onClick={() => setCreateForm({ ...createForm, password: `Pass-${Math.floor(1000 + Math.random() * 9000)}-2026!` })}
                    >
                      Generate Demo Pass
                    </button>
                  </div>
                  <input
                    type="text"
                    className="input"
                    required
                    value={createForm.password}
                    onChange={(e) => setCreateForm({ ...createForm, password: e.target.value })}
                  />
                  <small>Bank security standard (minimum 8 characters)</small>
                </div>
              </div>

              <div className="modal-foot" style={{ display: "flex", justifyContent: "flex-end", gap: 10, padding: "16px 24px", borderTop: "1px solid var(--line)", background: "var(--surface-2)" }}>
                <button
                  type="button"
                  className="btn secondary"
                  disabled={createBusy}
                  onClick={() => setCreateModalOpen(false)}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="btn primary"
                  disabled={createBusy || !createForm.username || !createForm.full_name || !createForm.email}
                >
                  {createBusy ? "Provisioning…" : "Provision Account"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal: Delete User Confirmation */}
      {deleteTarget && (
        <div className="modal-wrap" role="dialog" aria-modal="true" aria-labelledby="delete-modal-title">
          <div className="modal delete-user-modal" style={{ width: "min(460px, 100%)" }}>
            <div className="modal-head" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "18px 20px", borderBottom: "1px solid var(--line)" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <span style={{ width: 32, height: 32, borderRadius: 8, background: "var(--bad-soft)", color: "var(--bad)", display: "grid", placeItems: "center" }}>
                  <Trash size={18} />
                </span>
                <h2 id="delete-modal-title" style={{ margin: 0, fontSize: 16, fontWeight: 700, color: "var(--bad)" }}>
                  Delete Staff Account
                </h2>
              </div>
              <button
                className="icon-btn"
                aria-label="Close modal"
                disabled={deleteBusy}
                onClick={() => setDeleteTarget(null)}
              >
                <X size={18} />
              </button>
            </div>

            <div className="modal-body" style={{ padding: "18px 20px", display: "grid", gap: 12 }}>
              <p style={{ margin: 0, fontSize: 13.5, lineHeight: 1.5, color: "var(--text)" }}>
                Are you sure you want to permanently delete account <strong>@{deleteTarget.username}</strong> ({deleteTarget.full_name})?
              </p>
              <div style={{ padding: "10px 14px", borderRadius: 8, background: "var(--surface-2)", border: "1px solid var(--line)", fontSize: 12.5, display: "grid", gap: 4 }}>
                <div><strong>Role:</strong> {deleteTarget.role}</div>
                <div><strong>Email:</strong> {deleteTarget.email}</div>
                <div><strong>Branch:</strong> {deleteTarget.branch}</div>
              </div>
              <p style={{ margin: 0, fontSize: 12, color: "var(--bad)" }}>
                ⚠ Warning: This will immediately invalidate all active sessions, purge agent assignments, and revoke access to KURAL AVA operations.
              </p>
            </div>

            <div className="modal-foot" style={{ display: "flex", justifyContent: "flex-end", gap: 10, padding: "14px 20px", borderTop: "1px solid var(--line)", background: "var(--surface-2)" }}>
              <button
                type="button"
                className="btn secondary"
                disabled={deleteBusy}
                onClick={() => setDeleteTarget(null)}
              >
                Cancel
              </button>
              <button
                type="button"
                className="btn danger"
                disabled={deleteBusy}
                onClick={handleDeleteUserConfirm}
              >
                {deleteBusy ? "Deleting…" : "Confirm Delete"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
