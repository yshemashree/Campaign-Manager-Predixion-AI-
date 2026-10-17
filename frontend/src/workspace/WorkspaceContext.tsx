import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { useOrganizations, useWorkspaces } from "../api/queries";
import type { Organization, Workspace } from "../api/types";
import { useAuth } from "../auth/AuthContext";

const STORAGE_KEY = "cm.workspace";

interface WorkspaceState {
  workspaces: Workspace[];
  workspace: Workspace | null;
  workspaceId: string | null;
  setWorkspaceId: (id: string) => void;
  /** Organisations the user can see, by id (superadmins see all). */
  orgs: Map<string, Organization>;
  loading: boolean;
}

const WorkspaceContext = createContext<WorkspaceState | null>(null);

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const workspacesQuery = useWorkspaces(undefined, !!user);
  const orgsQuery = useOrganizations(!!user);
  const [selected, setSelected] = useState<string | null>(() => localStorage.getItem(STORAGE_KEY));

  const workspaces = useMemo(() => workspacesQuery.data ?? [], [workspacesQuery.data]);
  const workspace = workspaces.find((w) => w.id === selected) ?? workspaces[0] ?? null;

  const setWorkspaceId = useCallback((id: string) => {
    localStorage.setItem(STORAGE_KEY, id);
    setSelected(id);
  }, []);

  const orgs = useMemo(() => new Map((orgsQuery.data ?? []).map((o) => [o.id, o])), [orgsQuery.data]);

  const value = useMemo<WorkspaceState>(
    () => ({
      workspaces,
      workspace,
      workspaceId: workspace?.id ?? null,
      setWorkspaceId,
      orgs,
      loading: workspacesQuery.isPending,
    }),
    [workspaces, workspace, setWorkspaceId, orgs, workspacesQuery.isPending],
  );

  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

export function useWorkspace(): WorkspaceState {
  const ctx = useContext(WorkspaceContext);
  if (!ctx) throw new Error("useWorkspace must be used inside WorkspaceProvider");
  return ctx;
}
