import type { ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router";
import { useAuth } from "./auth/AuthContext";
import { PageSpinner } from "./components/Feedback";
import { AppShell } from "./layout/AppShell";
import { WorkspaceProvider } from "./workspace/WorkspaceContext";
import { LoginPage } from "./pages/LoginPage";
import { CampaignsPage } from "./pages/campaigns/CampaignsPage";
import { NewCampaignPage } from "./pages/campaigns/NewCampaignPage";
import { CampaignDetailPage } from "./pages/campaigns/CampaignDetailPage";
import { AgentsPage } from "./pages/agents/AgentsPage";
import { ConnectionsPage } from "./pages/ConnectionsPage";
import { WorkspacesPage } from "./pages/WorkspacesPage";
import { UsersPage } from "./pages/UsersPage";
import { OrganizationsPage } from "./pages/OrganizationsPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { DndPage } from "./pages/DndPage";

function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <PageSpinner />;
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  return <>{children}</>;
}

function AdminOnly({ superadmin = false, children }: { superadmin?: boolean; children: ReactNode }) {
  const { isAdmin, isSuperadmin } = useAuth();
  const allowed = superadmin ? isSuperadmin : isAdmin;
  return allowed ? <>{children}</> : <Navigate to="/campaigns" replace />;
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        element={
          <RequireAuth>
            <WorkspaceProvider>
              <AppShell />
            </WorkspaceProvider>
          </RequireAuth>
        }
      >
        <Route index element={<Navigate to="/campaigns" replace />} />
        <Route path="campaigns" element={<CampaignsPage />} />
        <Route path="campaigns/new" element={<NewCampaignPage />} />
        <Route path="campaigns/:campaignId" element={<CampaignDetailPage />} />
        <Route path="agents" element={<AgentsPage />} />
        <Route path="connections" element={<ConnectionsPage />} />
        <Route path="workspaces" element={<WorkspacesPage />} />
        <Route path="dnd" element={<DndPage />} />
        <Route
          path="users"
          element={
            <AdminOnly>
              <UsersPage />
            </AdminOnly>
          }
        />
        <Route
          path="organizations"
          element={
            <AdminOnly superadmin>
              <OrganizationsPage />
            </AdminOnly>
          }
        />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
