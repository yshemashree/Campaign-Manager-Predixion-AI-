import { useState, type KeyboardEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Pencil, PhoneCall, Plus, X } from "lucide-react";
import { fieldErrorsOf } from "../api/client";
import { connectionApi } from "../api/endpoints";
import { keys, useConnections } from "../api/queries";
import type { Connection, Workspace } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Button } from "../components/Button";
import { EmptyState, ErrorBanner, QueryError, SkeletonRows } from "../components/Feedback";
import { Field } from "../components/Field";
import { Modal } from "../components/Overlay";
import { PageHeader } from "../components/PageHeader";
import { useToast } from "../components/Toast";
import { RequireWorkspace } from "../layout/RequireWorkspace";
import { formatDateTime } from "../lib/format";

export function ConnectionsPage() {
  return <RequireWorkspace>{(ws) => <Connections workspace={ws} />}</RequireWorkspace>;
}

function Connections({ workspace }: { workspace: Workspace }) {
  const { isAdmin } = useAuth();
  const connections = useConnections(workspace.id);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<Connection | null>(null);

  const newButton = isAdmin && (
    <Button variant="primary" icon={<Plus size={16} />} onClick={() => setCreating(true)}>
      New connection
    </Button>
  );

  return (
    <>
      <PageHeader
        title="Connections"
        description={`Telephony connections and the caller numbers campaigns in ${workspace.name} dial from.`}
        actions={newButton}
      />
      <div className="card">
        {connections.isError ? (
          <QueryError error={connections.error} onRetry={() => connections.refetch()} />
        ) : connections.data?.length === 0 ? (
          <EmptyState icon={<PhoneCall size={20} />} title="No connections yet" action={newButton}>
            {isAdmin
              ? "Add the Sarvam connection ID and the numbers you call from."
              : "An admin needs to add a connection before campaigns can be created."}
          </EmptyState>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Connection ID</th>
                  <th>Caller numbers</th>
                  <th>Created</th>
                  {isAdmin && <th />}
                </tr>
              </thead>
              <tbody>
                {connections.isPending ? (
                  <SkeletonRows cols={isAdmin ? 5 : 4} rows={3} />
                ) : (
                  connections.data.map((c) => (
                    <tr key={c.id}>
                      <td className="cell-title">{c.name}</td>
                      <td className="mono">{c.connection_id}</td>
                      <td>
                        <div className="chip-list">
                          {c.caller_numbers.map((n) => (
                            <span key={n} className="chip mono">
                              {n}
                            </span>
                          ))}
                        </div>
                      </td>
                      <td className="muted nowrap">{formatDateTime(c.created_at)}</td>
                      {isAdmin && (
                        <td className="num">
                          <Button size="sm" variant="ghost" icon={<Pencil size={14} />} onClick={() => setEditing(c)}>
                            Edit
                          </Button>
                        </td>
                      )}
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>
      {creating && <ConnectionModal workspaceId={workspace.id} onClose={() => setCreating(false)} />}
      {editing && <ConnectionModal workspaceId={workspace.id} connection={editing} onClose={() => setEditing(null)} />}
    </>
  );
}

function ConnectionModal({
  workspaceId,
  connection,
  onClose,
}: {
  workspaceId: string;
  connection?: Connection;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [name, setName] = useState(connection?.name ?? "");
  const [connectionId, setConnectionId] = useState(connection?.connection_id ?? "");
  const [numbers, setNumbers] = useState<string[]>(connection?.caller_numbers ?? []);

  const save = useMutation({
    mutationFn: () => {
      const body = { name: name.trim(), connection_id: connectionId.trim(), caller_numbers: numbers };
      return connection ? connectionApi.update(connection.id, body) : connectionApi.create(workspaceId, body);
    },
    onSuccess: (saved) => {
      queryClient.invalidateQueries({ queryKey: keys.connections(workspaceId) });
      toast.success(connection ? "Connection saved" : "Connection created", saved.name);
      onClose();
    },
  });
  const errors = fieldErrorsOf(save.error);

  return (
    <Modal
      title={connection ? `Edit ${connection.name}` : "New connection"}
      onClose={onClose}
      onSubmit={() => save.mutate()}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="primary" loading={save.isPending}>
            {connection ? "Save changes" : "Create connection"}
          </Button>
        </>
      }
    >
      <div className="stack">
        {save.isError && <ErrorBanner error={save.error} shownFields={["name", "connection_id", "caller_numbers"]} />}
        <Field label="Name" error={errors.name}>
          <input className="input" value={name} onChange={(e) => setName(e.target.value)} autoFocus />
        </Field>
        <Field label="Connection ID" hint="The connection's ID in Sarvam" error={errors.connection_id}>
          <input className="input mono" value={connectionId} onChange={(e) => setConnectionId(e.target.value)} />
        </Field>
        <NumberListField numbers={numbers} onChange={setNumbers} error={errors.caller_numbers} />
      </div>
    </Modal>
  );
}

const E164 = /^\+[1-9]\d{6,14}$/;

function NumberListField({
  numbers,
  onChange,
  error,
}: {
  numbers: string[];
  onChange: (numbers: string[]) => void;
  error?: string;
}) {
  const [draft, setDraft] = useState("");
  const [localError, setLocalError] = useState("");

  function add() {
    const parts = draft
      .split(/[\s,;]+/)
      .map((p) => p.trim())
      .filter(Boolean);
    if (parts.length === 0) return;
    const bad = parts.filter((p) => !E164.test(p));
    if (bad.length) {
      setLocalError(`Use +E.164 format, e.g. +918069000001 (${bad.join(", ")})`);
      return;
    }
    onChange([...numbers, ...parts.filter((p) => !numbers.includes(p))]);
    setDraft("");
    setLocalError("");
  }

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      add();
    }
  }

  const message = localError || error;
  return (
    <div className="field">
      <label className="field__label" htmlFor="caller-number-input">
        Caller numbers
      </label>
      <div className="row">
        <input
          id="caller-number-input"
          className="input mono"
          placeholder="+918069000001"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKeyDown}
          aria-invalid={message ? true : undefined}
        />
        <Button onClick={add} disabled={!draft.trim()}>
          Add
        </Button>
      </div>
      {numbers.length > 0 && (
        <div className="chip-list" style={{ marginTop: 4 }}>
          {numbers.map((n) => (
            <span key={n} className="chip mono">
              {n}
              <button type="button" aria-label={`Remove ${n}`} onClick={() => onChange(numbers.filter((x) => x !== n))}>
                <X size={12} />
              </button>
            </span>
          ))}
        </div>
      )}
      {message ? (
        <span className="field__error">{message}</span>
      ) : (
        <span className="field__hint">Press Enter to add. You can paste several numbers separated by commas.</span>
      )}
    </div>
  );
}
