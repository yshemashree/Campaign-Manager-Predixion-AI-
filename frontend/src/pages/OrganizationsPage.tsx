import { useState, type ChangeEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Building2, Pencil, Plus } from "lucide-react";
import { fieldErrorsOf } from "../api/client";
import { orgApi } from "../api/endpoints";
import { keys, useOrganizations } from "../api/queries";
import type { Organization } from "../api/types";
import { Button } from "../components/Button";
import { EmptyState, ErrorBanner, QueryError, SkeletonRows } from "../components/Feedback";
import { Field, Switch } from "../components/Field";
import { Modal } from "../components/Overlay";
import { PageHeader } from "../components/PageHeader";
import { useToast } from "../components/Toast";
import { formatDateTime } from "../lib/format";

export function OrganizationsPage() {
  const orgs = useOrganizations();
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<Organization | null>(null);

  return (
    <>
      <PageHeader
        title="Organizations"
        description="Each organisation has its own limits on simultaneous live calls and calls per second."
        actions={
          <Button variant="primary" icon={<Plus size={16} />} onClick={() => setCreating(true)}>
            New organization
          </Button>
        }
      />
      <div className="card">
        {orgs.isError ? (
          <QueryError error={orgs.error} onRetry={() => orgs.refetch()} />
        ) : orgs.data?.length === 0 ? (
          <EmptyState icon={<Building2 size={20} />} title="No organizations yet">
            Create the first organisation and its admin account.
          </EmptyState>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Sarvam org ID</th>
                  <th className="num">Max live calls</th>
                  <th className="num">Max calls / sec</th>
                  <th>Status</th>
                  <th>Created</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {orgs.isPending ? (
                  <SkeletonRows cols={7} rows={3} />
                ) : (
                  orgs.data.map((org) => (
                    <tr key={org.id}>
                      <td className="cell-title">{org.name}</td>
                      <td className="mono">{org.sarvam_org_id ?? <span className="faint">—</span>}</td>
                      <td className="num">{org.max_concurrent_calls}</td>
                      <td className="num">{org.max_calls_per_second}</td>
                      <td>
                        <span className={`pill ${org.is_active ? "pill--green" : ""}`}>
                          {org.is_active ? "Active" : "Disabled"}
                        </span>
                      </td>
                      <td className="muted nowrap">{formatDateTime(org.created_at)}</td>
                      <td className="num">
                        <Button size="sm" variant="ghost" icon={<Pencil size={14} />} onClick={() => setEditing(org)}>
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
      {creating && <CreateOrgModal onClose={() => setCreating(false)} />}
      {editing && <EditOrgModal org={editing} onClose={() => setEditing(null)} />}
    </>
  );
}

function CreateOrgModal({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [form, setForm] = useState({
    name: "",
    sarvam_org_id: "",
    max_concurrent_calls: "5",
    max_calls_per_second: "5",
    admin_name: "",
    admin_email: "",
    admin_password: "",
  });
  const set = (key: keyof typeof form) => (e: ChangeEvent<HTMLInputElement>) =>
    setForm((f) => ({ ...f, [key]: e.target.value }));

  const create = useMutation({
    mutationFn: () =>
      orgApi.create({
        name: form.name.trim(),
        sarvam_org_id: form.sarvam_org_id.trim() || null,
        max_concurrent_calls: Number(form.max_concurrent_calls),
        max_calls_per_second: Number(form.max_calls_per_second),
        admin_email: form.admin_email.trim() || null,
        admin_password: form.admin_password || null,
        admin_name: form.admin_name.trim(),
      }),
    onSuccess: (org) => {
      queryClient.invalidateQueries({ queryKey: keys.orgs });
      toast.success("Organization created", org.name);
      onClose();
    },
  });
  const errors = fieldErrorsOf(create.error);
  const fields = Object.keys(form);

  return (
    <Modal
      title="New organization"
      description="Limits apply across every workspace and campaign in the organisation."
      onClose={onClose}
      onSubmit={() => create.mutate()}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="primary" loading={create.isPending}>
            Create organization
          </Button>
        </>
      }
    >
      <div className="stack">
        {create.isError && <ErrorBanner error={create.error} shownFields={fields} />}
        <div className="form-grid">
          <Field label="Name" error={errors.name} className="span-2">
            <input className="input" value={form.name} onChange={set("name")} autoFocus />
          </Field>
          <Field label="Sarvam org ID" optional error={errors.sarvam_org_id} className="span-2">
            <input className="input mono" value={form.sarvam_org_id} onChange={set("sarvam_org_id")} />
          </Field>
          <Field label="Max live calls" hint="Calls in progress at the same time" error={errors.max_concurrent_calls}>
            <input
              className="input"
              type="number"
              min={1}
              max={1000}
              value={form.max_concurrent_calls}
              onChange={set("max_concurrent_calls")}
            />
          </Field>
          <Field label="Max calls per second" hint="New calls started per second" error={errors.max_calls_per_second}>
            <input
              className="input"
              type="number"
              min={1}
              max={500}
              value={form.max_calls_per_second}
              onChange={set("max_calls_per_second")}
            />
          </Field>
        </div>
        <hr className="divider" />
        <div>
          <div className="section-title" style={{ marginBottom: 2 }}>
            First admin
          </div>
          <p className="muted small">Optional. Creates an org admin who can then add workspaces and users.</p>
        </div>
        <div className="form-grid">
          <Field label="Admin email" error={errors.admin_email}>
            <input className="input" type="email" value={form.admin_email} onChange={set("admin_email")} />
          </Field>
          <Field label="Admin name" optional error={errors.admin_name}>
            <input className="input" value={form.admin_name} onChange={set("admin_name")} />
          </Field>
          <Field label="Admin password" hint="At least 8 characters" error={errors.admin_password} className="span-2">
            <input
              className="input"
              type="password"
              autoComplete="new-password"
              value={form.admin_password}
              onChange={set("admin_password")}
            />
          </Field>
        </div>
      </div>
    </Modal>
  );
}

function EditOrgModal({ org, onClose }: { org: Organization; onClose: () => void }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [form, setForm] = useState({
    name: org.name,
    sarvam_org_id: org.sarvam_org_id ?? "",
    max_concurrent_calls: String(org.max_concurrent_calls),
    max_calls_per_second: String(org.max_calls_per_second),
  });
  const [active, setActive] = useState(org.is_active);
  const set = (key: keyof typeof form) => (e: ChangeEvent<HTMLInputElement>) =>
    setForm((f) => ({ ...f, [key]: e.target.value }));

  const save = useMutation({
    mutationFn: () =>
      orgApi.update(org.id, {
        name: form.name.trim(),
        sarvam_org_id: form.sarvam_org_id.trim() || null,
        max_concurrent_calls: Number(form.max_concurrent_calls),
        max_calls_per_second: Number(form.max_calls_per_second),
        is_active: active,
      }),
    onSuccess: (updated) => {
      queryClient.invalidateQueries({ queryKey: keys.orgs });
      toast.success("Limits saved", `${updated.name} now allows ${updated.max_calls_per_second} calls/s.`);
      onClose();
    },
  });
  const errors = fieldErrorsOf(save.error);

  return (
    <Modal
      title={`Edit ${org.name}`}
      description="New limits take effect within a second for every worker."
      onClose={onClose}
      onSubmit={() => save.mutate()}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="primary" loading={save.isPending}>
            Save changes
          </Button>
        </>
      }
    >
      <div className="stack">
        {save.isError && <ErrorBanner error={save.error} shownFields={[...Object.keys(form), "is_active"]} />}
        <div className="form-grid">
          <Field label="Name" error={errors.name} className="span-2">
            <input className="input" value={form.name} onChange={set("name")} />
          </Field>
          <Field label="Sarvam org ID" optional error={errors.sarvam_org_id} className="span-2">
            <input className="input mono" value={form.sarvam_org_id} onChange={set("sarvam_org_id")} />
          </Field>
          <Field label="Max live calls" error={errors.max_concurrent_calls}>
            <input
              className="input"
              type="number"
              min={1}
              max={1000}
              value={form.max_concurrent_calls}
              onChange={set("max_concurrent_calls")}
            />
          </Field>
          <Field label="Max calls per second" error={errors.max_calls_per_second}>
            <input
              className="input"
              type="number"
              min={1}
              max={500}
              value={form.max_calls_per_second}
              onChange={set("max_calls_per_second")}
            />
          </Field>
        </div>
        <label className="row" style={{ justifyContent: "space-between" }}>
          <span>
            <span className="field__label">Active</span>
            <span className="field__hint" style={{ display: "block" }}>
              A disabled organisation places no calls.
            </span>
          </span>
          <Switch checked={active} onChange={setActive} label="Active" />
        </label>
      </div>
    </Modal>
  );
}
