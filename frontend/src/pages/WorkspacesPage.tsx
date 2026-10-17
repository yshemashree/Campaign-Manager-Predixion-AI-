import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { LayoutGrid, Pencil, Plus } from "lucide-react";
import { fieldErrorsOf } from "../api/client";
import { workspaceApi } from "../api/endpoints";
import type { Workspace, WorkspaceInput } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Button } from "../components/Button";
import { EmptyState, ErrorBanner, PageSpinner } from "../components/Feedback";
import { Field } from "../components/Field";
import { Modal } from "../components/Overlay";
import { PageHeader } from "../components/PageHeader";
import { useToast } from "../components/Toast";
import { formatDateTime } from "../lib/format";
import { useWorkspace } from "../workspace/WorkspaceContext";

export function WorkspacesPage() {
  const { isAdmin, isSuperadmin } = useAuth();
  const { workspaces, workspaceId, setWorkspaceId, orgs, loading } = useWorkspace();
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<Workspace | null>(null);

  if (loading) return <PageSpinner />;

  return (
    <>
      <PageHeader
        title="Workspaces"
        description={
          isAdmin
            ? "Each workspace holds its own agents, connections and campaigns, with its own Sarvam credentials."
            : "The workspaces you are a member of."
        }
        actions={
          isAdmin && (
            <Button variant="primary" icon={<Plus size={16} />} onClick={() => setCreating(true)}>
              New workspace
            </Button>
          )
        }
      />
      <div className="card">
        {workspaces.length === 0 ? (
          <EmptyState
            icon={<LayoutGrid size={20} />}
            title="No workspaces yet"
            action={
              isAdmin && (
                <Button variant="primary" icon={<Plus size={16} />} onClick={() => setCreating(true)}>
                  New workspace
                </Button>
              )
            }
          >
            {isAdmin ? "Create a workspace to start adding agents and campaigns." : "Ask an admin to add you to one."}
          </EmptyState>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Name</th>
                  {isSuperadmin && <th>Organization</th>}
                  <th>Sarvam workspace ID</th>
                  <th>API key</th>
                  <th>Created</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {workspaces.map((ws) => (
                  <tr key={ws.id}>
                    <td>
                      <span className="cell-title">{ws.name}</span>
                      {ws.id === workspaceId && (
                        <span className="pill pill--plain pill--blue" style={{ marginLeft: 8 }}>
                          Current
                        </span>
                      )}
                    </td>
                    {isSuperadmin && <td>{orgs.get(ws.org_id)?.name ?? "—"}</td>}
                    <td className="mono">{ws.sarvam_workspace_id ?? <span className="faint">—</span>}</td>
                    <td>
                      {ws.sarvam_api_key_last4 ? (
                        <span className="secret">•••• {ws.sarvam_api_key_last4}</span>
                      ) : (
                        <span className="pill pill--amber">Not set</span>
                      )}
                    </td>
                    <td className="muted nowrap">{formatDateTime(ws.created_at)}</td>
                    <td className="num nowrap">
                      {ws.id !== workspaceId && (
                        <Button size="sm" variant="ghost" onClick={() => setWorkspaceId(ws.id)}>
                          Switch to
                        </Button>
                      )}
                      {isAdmin && (
                        <Button size="sm" variant="ghost" icon={<Pencil size={14} />} onClick={() => setEditing(ws)}>
                          Edit
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      {creating && <WorkspaceModal onClose={() => setCreating(false)} />}
      {editing && <WorkspaceModal workspace={editing} onClose={() => setEditing(null)} />}
    </>
  );
}

function WorkspaceModal({ workspace, onClose }: { workspace?: Workspace; onClose: () => void }) {
  const { isSuperadmin } = useAuth();
  const { orgs, setWorkspaceId } = useWorkspace();
  const queryClient = useQueryClient();
  const toast = useToast();
  const editing = !!workspace;

  const [name, setName] = useState(workspace?.name ?? "");
  const [sarvamId, setSarvamId] = useState(workspace?.sarvam_workspace_id ?? "");
  const [apiKey, setApiKey] = useState("");
  const [orgId, setOrgId] = useState(() => [...orgs.keys()][0] ?? "");

  const save = useMutation({
    mutationFn: () => {
      const body: WorkspaceInput = { name: name.trim(), sarvam_workspace_id: sarvamId.trim() || null };
      // The key is write-only: send it only when the user typed a new one.
      if (apiKey) body.sarvam_api_key = apiKey;
      return editing
        ? workspaceApi.update(workspace.id, body)
        : workspaceApi.create(body, isSuperadmin ? orgId : undefined);
    },
    onSuccess: (ws) => {
      queryClient.invalidateQueries({ queryKey: ["workspaces"] });
      toast.success(editing ? "Workspace saved" : "Workspace created", ws.name);
      if (!editing) setWorkspaceId(ws.id);
      onClose();
    },
  });
  const errors = fieldErrorsOf(save.error);

  return (
    <Modal
      title={editing ? `Edit ${workspace.name}` : "New workspace"}
      onClose={onClose}
      onSubmit={() => save.mutate()}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="primary" loading={save.isPending}>
            {editing ? "Save changes" : "Create workspace"}
          </Button>
        </>
      }
    >
      <div className="stack">
        {save.isError && <ErrorBanner error={save.error} shownFields={["name", "sarvam_workspace_id", "sarvam_api_key"]} />}
        {isSuperadmin && !editing && (
          <Field label="Organization">
            <select className="select" value={orgId} onChange={(e) => setOrgId(e.target.value)}>
              {[...orgs.values()].map((o) => (
                <option key={o.id} value={o.id}>
                  {o.name}
                </option>
              ))}
            </select>
          </Field>
        )}
        <Field label="Name" error={errors.name}>
          <input className="input" value={name} onChange={(e) => setName(e.target.value)} autoFocus />
        </Field>
        <Field label="Sarvam workspace ID" optional error={errors.sarvam_workspace_id}>
          <input className="input mono" value={sarvamId} onChange={(e) => setSarvamId(e.target.value)} />
        </Field>
        <Field
          label={editing ? "Replace API key" : "Sarvam API key"}
          optional={!editing}
          error={errors.sarvam_api_key}
          hint={
            editing ? (
              workspace.sarvam_api_key_last4 ? (
                <>
                  Current key ends in <span className="secret">•••• {workspace.sarvam_api_key_last4}</span>. Leave blank
                  to keep it.
                </>
              ) : (
                "No key is set yet. Campaigns in this workspace can't place calls until one is."
              )
            ) : (
              "Stored encrypted and never shown again; only the last four characters are displayed."
            )
          }
        >
          <input
            className="input mono"
            type="password"
            autoComplete="off"
            placeholder={editing ? "Paste a new key" : ""}
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
          />
        </Field>
      </div>
    </Modal>
  );
}
