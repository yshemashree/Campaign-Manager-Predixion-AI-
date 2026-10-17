import type { ReactNode } from "react";
import { Link } from "react-router";
import { LayoutGrid } from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import { EmptyState, PageSpinner } from "../components/Feedback";
import type { Workspace } from "../api/types";
import { useWorkspace } from "../workspace/WorkspaceContext";

/** Renders its children with the selected workspace, or explains why there isn't one. */
export function RequireWorkspace({ children }: { children: (workspace: Workspace) => ReactNode }) {
  const { workspace, loading } = useWorkspace();
  const { isAdmin } = useAuth();
  if (loading) return <PageSpinner />;
  if (!workspace) {
    return (
      <div className="card">
        <EmptyState
          icon={<LayoutGrid size={20} />}
          title="No workspace to show"
          action={
            isAdmin ? (
              <Link to="/workspaces" className="btn btn--primary">
                Go to workspaces
              </Link>
            ) : undefined
          }
        >
          {isAdmin
            ? "Campaigns, agents and connections live inside a workspace. Create one to get started."
            : "You haven't been added to a workspace yet. Ask your organisation admin to add you."}
        </EmptyState>
      </div>
    );
  }
  return <>{children(workspace)}</>;
}
