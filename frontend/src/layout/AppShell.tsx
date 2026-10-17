import { NavLink, Outlet, useNavigate } from "react-router";
import { AudioLines, Bot, Building2, LayoutGrid, LogOut, Megaphone, PhoneCall, PhoneOff, Users } from "lucide-react";
import type { ReactNode } from "react";
import { useAuth, useUser } from "../auth/AuthContext";
import { roleLabel } from "../components/StatusPill";
import { useWorkspace } from "../workspace/WorkspaceContext";
import { Button } from "../components/Button";

interface NavItem {
  to: string;
  label: string;
  icon: ReactNode;
  show: boolean;
}

export function AppShell() {
  const user = useUser();
  const { logout, isAdmin, isSuperadmin } = useAuth();
  const navigate = useNavigate();

  const work: NavItem[] = [
    { to: "/campaigns", label: "Outbound Campaigns", icon: <Megaphone size={17} />, show: true },
    { to: "/agents", label: "Agents", icon: <Bot size={17} />, show: true },
    { to: "/connections", label: "Connections", icon: <PhoneCall size={17} />, show: true },
  ];
  const admin: NavItem[] = [
    { to: "/workspaces", label: "Workspaces", icon: <LayoutGrid size={17} />, show: true },
    { to: "/users", label: "Users", icon: <Users size={17} />, show: isAdmin },
    { to: "/dnd", label: "Do Not Disturb", icon: <PhoneOff size={17} />, show: true },
    { to: "/organizations", label: "Organizations", icon: <Building2 size={17} />, show: isSuperadmin },
  ];

  const renderLinks = (items: NavItem[]) =>
    items
      .filter((i) => i.show)
      .map((i) => (
        <NavLink key={i.to} to={i.to} className="nav__link">
          {i.icon}
          {i.label}
        </NavLink>
      ));

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand__mark">
            <AudioLines size={16} />
          </span>
          Campaign Manager
        </div>
        <nav className="nav" aria-label="Main">
          <div className="nav__section">Deploy</div>
          {renderLinks(work)}
          <div className="nav__section">Settings</div>
          {renderLinks(admin)}
        </nav>
        <div className="sidebar__footer small faint">Outbound voice campaigns</div>
      </aside>

      <div className="main">
        <header className="topbar">
          <WorkspaceSwitcher />
          <div className="spacer" />
          <div className="user-chip">
            <span className="avatar" aria-hidden>
              {(user.full_name || user.email).slice(0, 1)}
            </span>
            <div className="user-chip__text">
              <span className="user-chip__email">{user.email}</span>
              <span className="user-chip__role">{roleLabel(user.role)}</span>
            </div>
            <Button
              variant="ghost"
              size="sm"
              icon={<LogOut size={15} />}
              onClick={() => {
                logout();
                navigate("/login", { replace: true });
              }}
            >
              Log out
            </Button>
          </div>
        </header>
        <main className="content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

function WorkspaceSwitcher() {
  const { workspaces, workspaceId, setWorkspaceId, orgs, loading } = useWorkspace();
  const { isSuperadmin } = useAuth();

  if (loading) return <span className="skeleton" style={{ width: 220, height: 32 }} />;
  if (workspaces.length === 0) return <span className="muted small">No workspaces yet</span>;

  // Superadmins see every organisation's workspaces, so group them.
  const groups = new Map<string, typeof workspaces>();
  for (const ws of workspaces) {
    const key = isSuperadmin ? (orgs.get(ws.org_id)?.name ?? "Other") : "";
    groups.set(key, [...(groups.get(key) ?? []), ws]);
  }

  return (
    <div className="ws-switcher">
      <label htmlFor="ws-switcher">Workspace</label>
      <select
        id="ws-switcher"
        className="select"
        value={workspaceId ?? ""}
        onChange={(e) => setWorkspaceId(e.target.value)}
      >
        {[...groups.entries()].map(([org, items]) =>
          org ? (
            <optgroup key={org} label={org}>
              {items.map((ws) => (
                <option key={ws.id} value={ws.id}>
                  {ws.name}
                </option>
              ))}
            </optgroup>
          ) : (
            items.map((ws) => (
              <option key={ws.id} value={ws.id}>
                {ws.name}
              </option>
            ))
          ),
        )}
      </select>
    </div>
  );
}
