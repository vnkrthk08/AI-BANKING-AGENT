import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ChartBar,
  Headset,
  MagnifyingGlass,
  Megaphone,
  Moon,
  Phone,
  ShieldCheck,
  SignOut,
  Sun,
  Tray,
  UsersThree,
} from "@phosphor-icons/react";
import { useAuth } from "../auth/AuthContext";
import { allowedHubs } from "../config/hubs";

interface CommandItem {
  id: string;
  title: string;
  category: "Navigation" | "Actions";
  description?: string;
  icon: React.ReactNode;
  perform: () => void;
  permission?: string;
}

export function CommandPalette({
  open,
  onClose,
  onToggleTheme,
  isDark,
}: {
  open: boolean;
  onClose: () => void;
  onToggleTheme: () => void;
  isDark: boolean;
}) {
  const navigate = useNavigate();
  const { user, logout } = useAuth();
  const [query, setQuery] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const allowed = allowedHubs(user?.permissions);

  const commands: CommandItem[] = [
    // Hub Navigation
    ...(allowed.includes("executive")
      ? [
          {
            id: "nav-overview",
            title: "Overview",
            category: "Navigation" as const,
            description: "Today's metrics and call volume",
            icon: <ChartBar size={18} />,
            perform: () => navigate("/executive"),
          },
        ]
      : []),
    ...(allowed.includes("test-console")
      ? [
          {
            id: "nav-voice",
            title: "Voice Studio",
            category: "Navigation" as const,
            description: "Place supervised browser voice calls",
            icon: <Headset size={18} />,
            perform: () => navigate("/test-console"),
          },
        ]
      : []),
    ...(allowed.includes("calls")
      ? [
          {
            id: "nav-calls",
            title: "Calls",
            category: "Navigation" as const,
            description: "Call logs, transcripts and customer directory",
            icon: <Phone size={18} />,
            perform: () => navigate("/calls"),
          },
        ]
      : []),
    ...(allowed.includes("work")
      ? [
          {
            id: "nav-work",
            title: "Work Queue",
            category: "Navigation" as const,
            description: "Escalated cases and due callbacks",
            icon: <Tray size={18} />,
            perform: () => navigate("/work"),
          },
        ]
      : []),
    ...(allowed.includes("campaigns")
      ? [
          {
            id: "nav-campaigns",
            title: "Campaigns",
            category: "Navigation" as const,
            description: "Outbound service campaigns and contacts",
            icon: <Megaphone size={18} />,
            perform: () => navigate("/campaigns"),
          },
        ]
      : []),
    ...(allowed.includes("team")
      ? [
          {
            id: "nav-team",
            title: "Team",
            category: "Navigation" as const,
            description: "Agent roster, availability and workload",
            icon: <UsersThree size={18} />,
            perform: () => navigate("/team"),
          },
        ]
      : []),
    ...(allowed.includes("governance")
      ? [
          {
            id: "nav-governance",
            title: "Governance",
            category: "Navigation" as const,
            description: "Integration health and audit controls",
            icon: <ShieldCheck size={18} />,
            perform: () => navigate("/governance"),
          },
        ]
      : []),

    // Quick Actions
    {
      id: "act-theme",
      title: isDark ? "Switch to Light Theme" : "Switch to Dark Theme",
      category: "Actions" as const,
      description: "Toggle interface appearance",
      icon: isDark ? <Sun size={18} /> : <Moon size={18} />,
      perform: onToggleTheme,
    },
    {
      id: "act-logout",
      title: "Sign Out",
      category: "Actions" as const,
      description: "End current operations session",
      icon: <SignOut size={18} />,
      perform: () => void logout(),
    },
  ];

  const filtered = commands.filter((c) => {
    if (!query.trim()) return true;
    const q = query.toLowerCase();
    return c.title.toLowerCase().includes(q) || (c.description?.toLowerCase().includes(q) ?? false);
  });

  useEffect(() => {
    setSelectedIndex(0);
  }, [query]);

  useEffect(() => {
    if (open) {
      setQuery("");
      setSelectedIndex(0);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [open]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (!open) return;
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      } else if (e.key === "ArrowDown") {
        e.preventDefault();
        setSelectedIndex((prev) => (prev + 1) % Math.max(1, filtered.length));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setSelectedIndex((prev) => (prev - 1 + filtered.length) % Math.max(1, filtered.length));
      } else if (e.key === "Enter") {
        e.preventDefault();
        if (filtered[selectedIndex]) {
          filtered[selectedIndex].perform();
          onClose();
        }
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [open, filtered, selectedIndex, onClose]);

  if (!open) return null;

  return (
    <div className="cmd-backdrop" onClick={onClose}>
      <div className="cmd-modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Command Palette">
        <div className="cmd-search-wrap">
          <MagnifyingGlass size={20} />
          <input
            ref={inputRef}
            className="cmd-input"
            placeholder="Type a command or jump to hub..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Search commands"
          />
          <kbd className="cmd-kbd">ESC</kbd>
        </div>

        <div className="cmd-list" role="listbox">
          {filtered.length === 0 ? (
            <div style={{ padding: "24px 16px", textAlign: "center", color: "var(--text-3)", fontSize: 13 }}>
              No commands found for "{query}"
            </div>
          ) : (
            filtered.map((cmd, idx) => (
              <button
                key={cmd.id}
                role="option"
                aria-selected={idx === selectedIndex}
                className={`cmd-item ${idx === selectedIndex ? "selected" : ""}`}
                onClick={() => {
                  cmd.perform();
                  onClose();
                }}
                onMouseEnter={() => setSelectedIndex(idx)}
              >
                {cmd.icon}
                <span style={{ fontWeight: 550 }}>{cmd.title}</span>
                {cmd.description && <span className="cmd-item-desc">{cmd.description}</span>}
              </button>
            ))
          )}
        </div>

        <div className="cmd-foot">
          <span>
            <kbd className="cmd-kbd" style={{ marginRight: 4 }}>↑</kbd>
            <kbd className="cmd-kbd" style={{ marginRight: 6 }}>↓</kbd>
            Navigate
          </span>
          <span>
            <kbd className="cmd-kbd" style={{ marginRight: 4 }}>↵</kbd>
            Select
          </span>
          <span style={{ marginLeft: "auto" }}>KURAL AVA QuickNav</span>
        </div>
      </div>
    </div>
  );
}
