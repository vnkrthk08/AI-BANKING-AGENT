import { useEffect, useState, type ReactElement } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { Bell, ChartBar, Headset, List, Megaphone, Moon, Phone, ShieldCheck, SignOut, Sun, Tray, UsersThree } from "@phosphor-icons/react";
import { ROLE_ACCESS, type RouteKey } from "../config/permissions";
import { useRole } from "../hooks/useRole";
import { useAuth } from "../auth/AuthContext";
import { useApi } from "../hooks/useApi";
import { apiJson } from "../services/http";
import { fmtRelative } from "./ui";

const NAV: { key: RouteKey; to: string; label: string; icon: ReactElement; group: string }[] = [
  { key: "executive", to: "/executive", label: "Overview", icon: <ChartBar size={18} />, group: "Operate" },
  { key: "test-console", to: "/test-console", label: "Voice Studio", icon: <Headset size={18} />, group: "Operate" },
  { key: "calls", to: "/calls", label: "Calls", icon: <Phone size={18} />, group: "Operate" },
  { key: "work", to: "/work", label: "Work Queue", icon: <Tray size={18} />, group: "Operate" },
  { key: "campaigns", to: "/campaigns", label: "Campaigns", icon: <Megaphone size={18} />, group: "Manage" },
  { key: "team", to: "/team", label: "Team", icon: <UsersThree size={18} />, group: "Manage" },
  { key: "governance", to: "/governance", label: "Governance", icon: <ShieldCheck size={18} />, group: "Control" },
];

interface Health { components: { key: string; status: string }[]; dialing: { stopped: boolean } }
interface Notif { id: string; title: string; message: string; is_read: boolean; created_at: string; link_url: string | null }

function StatusLine() {
  const { data, error } = useApi<Health>("/api/system/health");
  if (error) return <div className="badge bad">Backend unreachable</div>;
  if (!data) return <div className="badge plain">Checking services…</div>;
  const st = (k: string) => data.components.find((c) => c.key === k)?.status;
  const voice = st("stt") === "CONFIGURED" && st("tts") === "CONFIGURED";
  return (
    <>
      <span className={`badge ${st("database") === "HEALTHY" ? "ok" : "bad"}`}>Database {st("database") === "HEALTHY" ? "healthy" : "issue"}</span>
      <span className={`badge ${voice ? "ok" : "warn"}`}>Voice {voice ? "configured" : "not configured"}</span>
      <span className={`badge ${st("telephony") === "HEALTHY" ? "ok" : ""}`}>Telephony {st("telephony") === "HEALTHY" ? "live" : "off"}</span>
      {data.dialing.stopped && <span className="badge bad">Dialing stopped</span>}
    </>
  );
}

function Inbox() {
  const [open, setOpen] = useState(false);
  const { data, reload } = useApi<{ notifications: Notif[]; unread_count: number }>("/api/notifications?limit=20");
  const markAll = async () => { await apiJson("/api/notifications/read-all", { method: "POST" }); void reload(); };
  return (
    <div style={{ position: "relative" }}>
      <button className="icon-btn" aria-label={`Notifications (${data?.unread_count ?? 0} unread)`} onClick={() => setOpen((v) => !v)}>
        <Bell size={18} />{(data?.unread_count ?? 0) > 0 && <span className="dot" />}
      </button>
      {open && (
        <div className="popover" role="dialog" aria-label="Notifications">
          <div className="popover-head"><span>Notifications</span>{(data?.unread_count ?? 0) > 0 && <button className="btn sm ghost" onClick={markAll}>Mark all read</button>}</div>
          {!data?.notifications.length && <div className="empty" style={{ padding: 28 }}><p>No notifications yet.</p></div>}
          {data?.notifications.map((n) => (
            <div key={n.id} className={`notif ${n.is_read ? "" : "unread"}`}><b>{n.title}</b><div>{n.message}</div><small>{fmtRelative(n.created_at)}</small></div>
          ))}
        </div>
      )}
    </div>
  );
}

export function AppShell() {
  const [role] = useRole();
  const { user, logout } = useAuth();
  const location = useLocation();
  const [navOpen, setNavOpen] = useState(false);
  const [dark, setDark] = useState(() => { try { return localStorage.getItem("kural-theme") === "dark"; } catch { return false; } });
  useEffect(() => { document.documentElement.dataset.theme = dark ? "dark" : "light"; try { localStorage.setItem("kural-theme", dark ? "dark" : "light"); } catch { /* ignore */ } }, [dark]);
  useEffect(() => setNavOpen(false), [location.pathname]);
  const allowed = ROLE_ACCESS[role].routes;
  const items = NAV.filter((n) => allowed.includes(n.key));
  const current = NAV.find((n) => location.pathname.startsWith(n.to));
  const initials = (user?.full_name || user?.username || "?").split(" ").map((p) => p[0]).join("").slice(0, 2).toUpperCase();
  return (
    <div className={`app ${navOpen ? "nav-open" : ""}`}>
      <aside className="side" aria-label="Primary">
        <div className="side-brand"><span className="side-mark">K</span><div><b>KURAL AVA</b><small>Town Bank · Operations</small></div></div>
        {["Operate", "Manage", "Control"].map((g) => {
          const group = items.filter((i) => i.group === g);
          if (!group.length) return null;
          return <div key={g}><div className="side-label">{g}</div>{group.map((i) => <NavLink key={i.key} to={i.to} className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}>{i.icon}<span>{i.label}</span></NavLink>)}</div>;
        })}
        <div className="side-foot"><span>{user?.branch}</span><span style={{ color: "#6f82a0" }}>All times IST</span></div>
      </aside>
      <div className="main" onClick={() => navOpen && setNavOpen(false)}>
        <header className="topbar">
          <button className="icon-btn menu-btn" aria-label="Open navigation" onClick={(e) => { e.stopPropagation(); setNavOpen(true); }}><List size={20} /></button>
          <span className="crumb">{current?.label ?? "KURAL AVA"}</span>
          <span className="spacer" />
          <Inbox />
          <button className="icon-btn" aria-label="Toggle theme" onClick={() => setDark((v) => !v)}>{dark ? <Sun size={18} /> : <Moon size={18} />}</button>
          <div className="user"><span className="avatar">{initials}</span><div className="user-meta"><b>{user?.full_name || user?.username}</b><span>{ROLE_ACCESS[role].label}</span></div>
            <button className="icon-btn" aria-label="Sign out" title="Sign out" onClick={() => void logout()}><SignOut size={18} /></button></div>
        </header>
        <main className="content"><Outlet /></main>
      </div>
    </div>
  );
}

export { StatusLine };
