import {
  Bell,
  Briefcase,
  CaretLeft,
  CaretRight,
  ChartLineUp,
  Clock,
  FileText,
  House,
  ListChecks,
  MagnifyingGlass,
  Megaphone,
  Moon,
  Phone,
  ShieldCheck,
  SidebarSimple,
  Sun,
  UsersThree,
  WarningCircle,
  Waveform,
} from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";
import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";
import { ROLE_ACCESS, ROUTES, type RouteKey } from "../config/permissions";
import { FilterBar } from "./FilterBar";
import { useDashboard } from "../hooks/DashboardContext";
import { useRole } from "../hooks/useRole";
import { kuralApi, type AppNotification } from "../services/kuralApi";
import type { Role } from "../types";

const icons: Record<RouteKey, React.ReactNode> = {
  executive: <House size={18} />,
  "test-console": <Waveform size={18} />,
  calls: <Phone size={18} />,
  campaigns: <Megaphone size={18} />,
  work: <WarningCircle size={18} />,
  team: <UsersThree size={18} />,
  governance: <ShieldCheck size={18} />,
  // legacy icons for safety
  "my-work": <Briefcase size={18} />,
  "live-calls": <Phone size={18} />,
  "call-log": <ListChecks size={18} />,
  "customer-journey": <ChartLineUp size={18} />,
  callbacks: <Clock size={18} />,
  escalations: <WarningCircle size={18} />,
  insights: <ChartLineUp size={18} />,
  reports: <FileText size={18} />,
  compliance: <ShieldCheck size={18} />,
  "system-health": <Waveform size={18} />,
};

export function AppShell() {
  const [role, setRole] = useRole();
  const [collapsed, setCollapsed] = useState(false);
  const [dark, setDark] = useState(() => localStorage.getItem("kural-ops-theme") === "dark");
  const [searchOpen, setSearchOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [clock, setClock] = useState(() => new Date());

  // Real backend in-app notifications
  const [apiNotifications, setApiNotifications] = useState<AppNotification[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);

  const { snapshot } = useDashboard();
  const location = useLocation();
  const navigate = useNavigate();
  const access = ROLE_ACCESS[role];
  const route = (Object.keys(ROUTES) as RouteKey[]).find((key) => ROUTES[key].path === location.pathname);
  const usesFilters = route === "executive" || route === "calls" || route === "live-calls" || route === "call-log" || route === "insights";

  // Poll real notifications
  useEffect(() => {
    function fetchNotifs() {
      kuralApi
        .getNotifications()
        .then((res) => {
          setApiNotifications(res.notifications || []);
          setUnreadCount(res.unread_count || 0);
        })
        .catch(() => {});
    }
    fetchNotifs();
    const timer = window.setInterval(fetchNotifs, 10000);
    return () => window.clearInterval(timer);
  }, []);

  const searchResults = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (query.length < 2 || !snapshot) return [];
    return snapshot.calls
      .filter((call) =>
        role !== "AGENT" ||
        snapshot.escalations.some((item) => item.callId === call.id && (!item.assignedAgentId || item.assignedAgentId === "AG-001"))
      )
      .filter(
        (call) =>
          call.id.toLowerCase().includes(query) ||
          call.customerRef.toLowerCase().includes(query) ||
          call.maskedPhone.toLowerCase().includes(query) ||
          call.campaignName.toLowerCase().includes(query)
      )
      .slice(0, 6);
  }, [role, search, snapshot]);

  useEffect(() => {
    const interval = window.setInterval(() => setClock(new Date()), 30_000);
    const hotkey = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setSearchOpen((open) => !open);
      }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "b") {
        event.preventDefault();
        setCollapsed((c) => !c);
      }
      if (event.key === "Escape") {
        setSearchOpen(false);
        setNotificationsOpen(false);
      }
    };
    window.addEventListener("keydown", hotkey);
    return () => {
      window.clearInterval(interval);
      window.removeEventListener("keydown", hotkey);
    };
  }, []);

  useEffect(() => {
    document.documentElement.dataset.theme = dark ? "dark" : "light";
  }, [dark]);

  function switchRole(value: Role) {
    setRole(value);
    setNotificationsOpen(false);
    navigate(ROUTES[ROLE_ACCESS[value].home].path);
  }

  function openSearchResult(callId: string) {
    setSearchOpen(false);
    navigate(`/calls?query=${encodeURIComponent(callId)}`);
  }

  async function handleMarkAllRead() {
    await kuralApi.markAllNotificationsRead().catch(() => {});
    setUnreadCount(0);
    setApiNotifications((prev) => prev.map((n) => ({ ...n, is_read: true })));
  }

  async function handleNotificationClick(n: AppNotification) {
    if (!n.is_read) {
      kuralApi.markNotificationRead(n.id).catch(() => {});
      setUnreadCount((c) => Math.max(0, c - 1));
      setApiNotifications((prev) => prev.map((item) => (item.id === n.id ? { ...item, is_read: true } : item)));
    }
    setNotificationsOpen(false);
    if (n.link_url) {
      navigate(n.link_url);
    } else if (n.category === "CALLBACK" || n.category === "ESCALATION") {
      navigate("/work");
    } else if (n.category === "TELEPHONY") {
      navigate("/calls");
    }
  }

  const groups = ["WORKSPACE", "MANAGE", "GOVERNANCE"] as const;

  return (
    <div className={`ops-app ${collapsed ? "ops-sidebar-collapsed" : ""}`}>
      {/* SIDEBAR NAVIGATION RAIL */}
      <aside className="ops-sidebar">
        <Link
          className="ops-brand"
          to={ROUTES[access.home].path}
          onClick={
            collapsed
              ? (e) => {
                  e.preventDefault();
                  setCollapsed(false);
                }
              : undefined
          }
          title={collapsed ? "Expand sidebar" : undefined}
        >
          <span className="ops-brand-mark">K</span>
          <span className="ops-brand-copy">
            <strong>KURAL</strong>
            <small>OPERATIONS</small>
          </span>
        </Link>
        <div
          className="ops-workspace-switch"
          onClick={collapsed ? () => setCollapsed(false) : undefined}
          style={collapsed ? { cursor: "pointer" } : undefined}
          title={collapsed ? "Expand sidebar" : undefined}
        >
          <span className="ops-bank-avatar">TB</span>
          <span>
            <strong>Town Bank</strong>
            <small>Operations Hub · India</small>
          </span>
          <CaretRight size={15} />
        </div>
        <nav className="ops-nav" aria-label="Main navigation">
          {groups.map((group) => {
            const links = access.routes.filter(
              (key) => ROUTES[key].section === group && ["executive", "test-console", "calls", "campaigns", "work", "team", "governance"].includes(key)
            );
            if (!links.length) return null;
            return (
              <div className="ops-nav-group" key={group}>
                <span className="ops-nav-group-title">{group}</span>
                {links.map((key) => {
                  const active = route === key || (key === "calls" && (route === "live-calls" || route === "call-log" || route === "customer-journey")) || (key === "work" && (route === "escalations" || route === "callbacks"));
                  return (
                    <Link
                      key={key}
                      to={ROUTES[key].path}
                      className={`ops-nav-link ${active ? "active" : ""}`}
                      title={collapsed ? ROUTES[key].label : undefined}
                      aria-current={active ? "page" : undefined}
                    >
                      <span className="ops-nav-icon">{icons[key]}</span>
                      <span className="ops-nav-label">{ROUTES[key].label}</span>
                      {key === "work" && unreadCount > 0 && <span className="ops-nav-count">{unreadCount}</span>}
                    </Link>
                  );
                })}
              </div>
            );
          })}
        </nav>
        <div className="ops-sidebar-bottom">
          <div className="ops-live-status" title="Telephony & Core Voice Connected">
            <i />
            <span>Telephony &amp; Voice Online</span>
          </div>
          <button
            className="ops-collapse"
            onClick={() => setCollapsed((value) => !value)}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            title={collapsed ? "Expand menu (Ctrl + B)" : "Collapse menu (Ctrl + B)"}
          >
            {collapsed ? (
              <CaretRight size={18} weight="bold" />
            ) : (
              <>
                <CaretLeft size={18} weight="bold" />
                <span>Collapse menu</span>
              </>
            )}
          </button>
        </div>
      </aside>

      {/* MAIN VIEWPORT */}
      <div className="ops-main">
        <header className="ops-topbar">
          <div className="ops-breadcrumb">
            <button
              className="ops-icon-button ops-sidebar-toggle-btn"
              onClick={() => setCollapsed((v) => !v)}
              aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
              title={collapsed ? "Expand sidebar (Ctrl + B)" : "Collapse sidebar (Ctrl + B)"}
            >
              <SidebarSimple size={18} weight={collapsed ? "fill" : "regular"} />
            </button>
            <span>Town Bank</span>
            <span>/</span>
            <strong>{route ? ROUTES[route].label : "Operations Hub"}</strong>
          </div>
          <div className="ops-topbar-tools">
            <button className="ops-search-trigger" onClick={() => setSearchOpen((open) => !open)}>
              <MagnifyingGlass size={16} />
              <span>Search calls, customers…</span>
              <kbd>Ctrl K</kbd>
            </button>
            <span className="ops-clock">
              <Clock size={15} />
              <time>
                {new Intl.DateTimeFormat("en-IN", {
                  timeZone: "Asia/Kolkata",
                  hour: "2-digit",
                  minute: "2-digit",
                  hour12: true,
                }).format(clock)}{" "}
                IST
              </time>
            </span>

            {/* NOTIFICATIONS POPOVER */}
            <div className="ops-notice-wrap" style={{ position: "relative" }}>
              <button
                className="ops-icon-button ops-notification-button"
                onClick={() => setNotificationsOpen((open) => !open)}
                aria-label={`${unreadCount} notifications`}
              >
                <Bell size={18} />
                {unreadCount > 0 && <i>{Math.min(unreadCount, 99)}</i>}
              </button>
              {notificationsOpen && (
                <div
                  className="ops-notification-popover"
                  style={{
                    position: "absolute",
                    top: "120%",
                    right: 0,
                    width: "360px",
                    background: "var(--ops-card, #0f172a)",
                    border: "1px solid var(--ops-border, rgba(255, 255, 255, 0.12))",
                    borderRadius: "12px",
                    boxShadow: "0 12px 32px rgba(0, 0, 0, 0.5)",
                    zIndex: 100,
                    padding: "16px",
                  }}
                >
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      marginBottom: "12px",
                      paddingBottom: "8px",
                      borderBottom: "1px solid var(--ops-border, rgba(255, 255, 255, 0.08))",
                    }}
                  >
                    <div className="ops-popover-title" style={{ margin: 0, fontWeight: 700 }}>
                      Operations Alerts <span>({unreadCount})</span>
                    </div>
                    {unreadCount > 0 && (
                      <button
                        className="ops-button ops-button-sm"
                        onClick={handleMarkAllRead}
                        style={{ fontSize: "11px", padding: "2px 8px" }}
                      >
                        Mark All Read
                      </button>
                    )}
                  </div>
                  <div style={{ maxHeight: "280px", overflowY: "auto", display: "flex", flexDirection: "column", gap: "8px" }}>
                    {apiNotifications.length === 0 ? (
                      <p style={{ color: "var(--ops-muted)", fontSize: "12.5px", textAlign: "center", padding: "16px 0" }}>
                        No notifications right now. System operating normally.
                      </p>
                    ) : (
                      apiNotifications.map((n) => (
                        <div
                          key={n.id}
                          onClick={() => handleNotificationClick(n)}
                          style={{
                            padding: "8px 10px",
                            borderRadius: "6px",
                            background: n.is_read ? "transparent" : "rgba(13, 148, 136, 0.12)",
                            borderLeft: `3px solid ${
                              n.level === "WARNING" ? "#f59e0b" : n.level === "ERROR" ? "#ef4444" : "#10b981"
                            }`,
                            cursor: "pointer",
                            fontSize: "12px",
                          }}
                        >
                          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "2px" }}>
                            <strong>{n.title}</strong>
                            <small style={{ color: "var(--ops-muted)" }}>
                              {n.created_at ? new Date(n.created_at).toLocaleTimeString("en-IN") : ""}
                            </small>
                          </div>
                          <div style={{ color: "var(--ops-text)" }}>{n.message}</div>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              )}
            </div>

            <button
              className="ops-icon-button"
              aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}
              onClick={() => {
                const next = !dark;
                setDark(next);
                localStorage.setItem("kural-ops-theme", next ? "dark" : "light");
              }}
            >
              {dark ? <Sun size={17} /> : <Moon size={17} />}
            </button>
            <label className="ops-role-select">
              <span>ACTIVE ROLE</span>
              <select
                aria-label="Active role"
                value={role}
                onChange={(event) => switchRole(event.target.value as Role)}
              >
                {(Object.keys(ROLE_ACCESS) as Role[]).map((item) => (
                  <option key={item} value={item}>
                    {ROLE_ACCESS[item].label}
                  </option>
                ))}
              </select>
            </label>
            <div className="ops-user-avatar" title={role}>
              {role === "AGENT" ? "A1" : role === "SUPERVISOR" ? "S1" : role === "COMPLIANCE" ? "C1" : "O1"}
            </div>
          </div>
        </header>

        {usesFilters && <FilterBar />}
        <div className="ops-content">
          <Outlet context={{ role }} />
        </div>
        <footer className="ops-footer">
          <span>
            <i /> Town Bank Operations Intelligence · High-Volume Telephony Engine
          </span>
          <span>All timestamps Asia/Kolkata (IST)</span>
        </footer>
      </div>

      {/* SEARCH LAYER */}
      {searchOpen && (
        <div
          className="ops-search-layer"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setSearchOpen(false);
          }}
        >
          <section className="ops-search-dialog" role="dialog" aria-modal="true" aria-label="Search calls">
            <div className="ops-search-input-row">
              <MagnifyingGlass size={20} />
              <input
                autoFocus
                placeholder="Search masked customers, calls or campaigns"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && searchResults[0]) openSearchResult(searchResults[0].id);
                }}
              />
              <kbd>ESC</kbd>
            </div>
            <div className="ops-search-results">
              {search.length < 2 ? (
                <p>Search by call ID, customer reference, masked number or campaign.</p>
              ) : searchResults.length ? (
                searchResults.map((call) => (
                  <button key={call.id} onClick={() => openSearchResult(call.id)}>
                    <span>
                      <strong>{call.id}</strong>
                      <small>
                        {call.customerRef} · {call.maskedPhone}
                      </small>
                    </span>
                    <span>{call.campaignName}</span>
                  </button>
                ))
              ) : (
                <p>No matching masked records.</p>
              )}
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
