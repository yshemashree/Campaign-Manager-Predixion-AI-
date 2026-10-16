import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus, Users } from "lucide-react";
import { fieldErrorsOf } from "../api/client";
import { userApi } from "../api/endpoints";
import { useUsers } from "../api/queries";
import type { User, UserCreate, UserUpdate } from "../api/types";
import { useAuth, useUser } from "../auth/AuthContext";
import { Button } from "../components/Button";
import { EmptyState, ErrorBanner, QueryError, SkeletonRows } from "../components/Feedback";
import { Field, Switch } from "../components/Field";
import { Modal } from "../components/Overlay";
import { PageHeader } from "../components/PageHeader";
import { roleLabel } from "../components/StatusPill";
import { useToast } from "../components/Toast";
import { useWorkspace } from "../workspace/WorkspaceContext";

export function UsersPage() {
  const { isSuperadmin } = useAuth();
  const { workspaces, orgs } = useWorkspace();
  const [orgFilter, setOrgFilter] = useState("");
  const users = useUsers(isSuperadmin ? orgFilter || undefined : undefined);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<User | null>(null);
  const wsNames = new Map(workspaces.map((w) => [w.id, w.name]));

  return (
    <>
      <PageHeader
        title="Users"
        description="Org admins manage everything in their organisation. Members see only the workspaces they're added to."
        actions={
          <Button variant="primary" icon={<Plus size={16} />} onClick={() => setCreating(true)}>
            New user
          </Button>
        }
      />
      {isSuperadmin && (
        <div className="row" style={{ marginBottom: 12 }}>
          <label className="small muted" htmlFor="org-filter">
            Organization
          </label>
          <select
            id="org-filter"
            className="select select--sm"
            style={{ width: 240 }}
            value={orgFilter}
            onChange={(e) => setOrgFilter(e.target.value)}
          >
            <option value="">All organizations</option>
            {[...orgs.values()].map((o) => (
              <option key={o.id} value={o.id}>
                {o.name}
              </option>
            ))}
          </select>
        </div>
      )}
      <div className="card">
        {users.isError ? (
          <QueryError error={users.error} onRetry={() => users.refetch()} />
        ) : users.data?.length === 0 ? (
          <EmptyState icon={<Users size={20} />} title="No users yet">
            Add teammates so they can run campaigns.
          </EmptyState>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>User</th>
                  {isSuperadmin && <th>Organization</th>}
                  <th>Role</th>
                  <th>Workspaces</th>
                  <th>Status</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {users.isPending ? (
                  <SkeletonRows cols={isSuperadmin ? 6 : 5} rows={3} />
                ) : (
                  users.data.map((u) => (
                    <tr key={u.id}>
                      <td>
                        <div className="cell-title">{u.full_name || u.email}</div>
                        {u.full_name && <div className="cell-sub">{u.email}</div>}
                      </td>
                      {isSuperadmin && <td>{(u.org_id && orgs.get(u.org_id)?.name) ?? "—"}</td>}
                      <td>
                        <span className="tag-role">{roleLabel(u.role)}</span>
                      </td>
                      <td>
                        {u.role === "org_admin" ? (
                          <span className="muted">All workspaces</span>
                        ) : u.workspace_ids.length === 0 ? (
                          <span className="faint">None</span>
                        ) : (
                          <div className="chip-list">
                            {u.workspace_ids.map((id) => (
                              <span key={id} className="chip">
                                {wsNames.get(id) ?? "Workspace"}
                              </span>
                            ))}
                          </div>
                        )}
                      </td>
                      <td>
                        <span className={`pill ${u.is_active ? "pill--green" : ""}`}>
                          {u.is_active ? "Active" : "Disabled"}
                        </span>
                      </td>
                      <td className="num">
                        <Button size="sm" variant="ghost" icon={<Pencil size={14} />} onClick={() => setEditing(u)}>
                          Edit
                        </Button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>
      {creating && <UserModal onClose={() => setCreating(false)} defaultOrgId={orgFilter} />}
      {editing && <UserModal user={editing} onClose={() => setEditing(null)} />}
    </>
  );
}

function UserModal({ user, defaultOrgId, onClose }: { user?: User; defaultOrgId?: string; onClose: () => void }) {
  const me = useUser();
  const { isSuperadmin } = useAuth();
  const { workspaces, orgs } = useWorkspace();
  const queryClient = useQueryClient();
  const toast = useToast();
  const editing = !!user;

  const [orgId, setOrgId] = useState(user?.org_id ?? (defaultOrgId || me.org_id || [...orgs.keys()][0] || ""));
  const [email, setEmail] = useState(user?.email ?? "");
  const [fullName, setFullName] = useState(user?.full_name ?? "");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<"org_admin" | "member">(user?.role === "org_admin" ? "org_admin" : "member");
  const [wsIds, setWsIds] = useState<string[]>(user?.workspace_ids ?? []);
  const [active, setActive] = useState(user?.is_active ?? true);

  const orgWorkspaces = workspaces.filter((w) => w.org_id === orgId);

  const save = useMutation({
    mutationFn: () => {
      const workspace_ids = role === "member" ? wsIds.filter((id) => orgWorkspaces.some((w) => w.id === id)) : [];
      if (editing) {
        const body: UserUpdate = { full_name: fullName.trim(), role, workspace_ids, is_active: active };
        if (password) body.password = password;
        return userApi.update(user.id, body);
      }
      const body: UserCreate = { email: email.trim(), password, full_name: fullName.trim(), role, workspace_ids };
      if (isSuperadmin) body.org_id = orgId;
      return userApi.create(body);
    },
    onSuccess: (saved) => {
      queryClient.invalidateQueries({ queryKey: ["users"] });
      toast.success(editing ? "User saved" : "User created", saved.email);
      onClose();
    },
  });
  const errors = fieldErrorsOf(save.error);

  const toggleWs = (id: string) => setWsIds((ids) => (ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id]));

  return (
    <Modal
      title={editing ? `Edit ${user.email}` : "New user"}
      onClose={onClose}
      onSubmit={() => save.mutate()}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="primary" loading={save.isPending}>
            {editing ? "Save changes" : "Create user"}
          </Button>
        </>
      }
    >
      <div className="stack">
        {save.isError && (
          <ErrorBanner
            error={save.error}
            shownFields={["email", "password", "full_name", "role", "workspace_ids", "org_id"]}
          />
        )}
        {isSuperadmin && !editing && (
          <Field label="Organization" error={errors.org_id}>
            <select className="select" value={orgId} onChange={(e) => setOrgId(e.target.value)}>
              {[...orgs.values()].map((o) => (
                <option key={o.id} value={o.id}>
                  {o.name}
                </option>
              ))}
            </select>
          </Field>
        )}
        <div className="form-grid">
          {!editing && (
            <Field label="Email" error={errors.email}>
              <input
                className="input"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoFocus
              />
            </Field>
          )}
          <Field label="Full name" optional error={errors.full_name} className={editing ? "span-2" : undefined}>
            <input className="input" value={fullName} onChange={(e) => setFullName(e.target.value)} />
          </Field>
          <Field
            label={editing ? "New password" : "Password"}
            optional={editing}
            hint={editing ? "Leave blank to keep the current password" : "At least 8 characters"}
            error={errors.password}
          >
            <input
              className="input"
              type="password"
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </Field>
          <Field label="Role" error={errors.role}>
            <select className="select" value={role} onChange={(e) => setRole(e.target.value as typeof role)}>
              <option value="member">Member</option>
              <option value="org_admin">Org admin</option>
            </select>
          </Field>
        </div>

        {role === "member" ? (
          <div className="field">
            <span className="field__label">Workspaces</span>
            {orgWorkspaces.length === 0 ? (
              <span className="field__hint">This organisation has no workspaces yet.</span>
            ) : (
              <div className="fieldset" style={{ padding: 12 }}>
                <div className="stack-sm">
                  {orgWorkspaces.map((w) => (
                    <label key={w.id} className="check">
                      <input type="checkbox" checked={wsIds.includes(w.id)} onChange={() => toggleWs(w.id)} />
                      {w.name}
                    </label>
                  ))}
                </div>
              </div>
            )}
            {errors.workspace_ids ? (
              <span className="field__error">{errors.workspace_ids}</span>
            ) : (
              <span className="field__hint">Members only see campaigns in these workspaces.</span>
            )}
          </div>
        ) : (
          <p className="muted small">Org admins can see and manage every workspace in the organisation.</p>
        )}

        {editing && (
          <label className="row" style={{ justifyContent: "space-between" }}>
            <span>
              <span className="field__label">Active</span>
              <span className="field__hint" style={{ display: "block" }}>
                Disabled users can't sign in.
              </span>
            </span>
            <Switch checked={active} onChange={setActive} label="Active" disabled={user.id === me.id} />
          </label>
        )}
      </div>
    </Modal>
  );
}
