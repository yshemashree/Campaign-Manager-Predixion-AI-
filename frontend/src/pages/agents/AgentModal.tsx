import { Fragment, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { fieldErrorsOf } from "../../api/client";
import { agentApi } from "../../api/endpoints";
import { keys } from "../../api/queries";
import { VARIABLE_TYPES, type Agent, type AgentInput, type VariableType } from "../../api/types";
import { Button } from "../../components/Button";
import { ErrorBanner } from "../../components/Feedback";
import { Field } from "../../components/Field";
import { Modal } from "../../components/Overlay";
import { useToast } from "../../components/Toast";

interface VariableRow {
  key: number;
  name: string;
  type: VariableType;
  required: boolean;
  example: string;
  allowed: string;
  max_length?: number;
}

const BASE_FIELDS = ["name", "app_id", "app_version", "initial_bot_message", "initial_state_name", "variables"];

export function AgentModal({ workspaceId, agent, onClose }: { workspaceId: string; agent?: Agent; onClose: () => void }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const nextKey = useRef(1);
  const newKey = () => nextKey.current++;

  const [name, setName] = useState(agent?.name ?? "");
  const [appId, setAppId] = useState(agent?.app_id ?? "");
  const [appVersion, setAppVersion] = useState(String(agent?.app_version ?? 1));
  const [greeting, setGreeting] = useState(agent?.initial_bot_message ?? "");
  const [stateName, setStateName] = useState(agent?.initial_state_name ?? "");
  const [rows, setRows] = useState<VariableRow[]>(() =>
    (agent?.variables ?? []).map((v) => ({
      key: newKey(),
      name: v.name,
      type: v.type,
      required: v.required,
      example: v.example ?? "",
      allowed: (v.allowed ?? []).join(", "),
      max_length: v.max_length,
    })),
  );

  const update = (key: number, patch: Partial<VariableRow>) =>
    setRows((all) => all.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  const addRow = () =>
    setRows((all) => [...all, { key: newKey(), name: "", type: "string", required: true, example: "", allowed: "" }]);

  const save = useMutation({
    mutationFn: () => {
      const body: AgentInput = {
        name: name.trim(),
        app_id: appId.trim(),
        app_version: Number(appVersion),
        initial_bot_message: greeting.trim() || null,
        initial_state_name: stateName.trim() || null,
        variables: rows.map((r) => ({
          name: r.name.trim(),
          type: r.type,
          required: r.required,
          example: r.example.trim(),
          allowed:
            r.type === "enum"
              ? r.allowed
                  .split(",")
                  .map((s) => s.trim())
                  .filter(Boolean)
              : [],
          ...(r.max_length ? { max_length: r.max_length } : {}),
        })),
      };
      return agent ? agentApi.update(agent.id, body) : agentApi.create(workspaceId, body);
    },
    onSuccess: (saved) => {
      queryClient.invalidateQueries({ queryKey: keys.agents(workspaceId) });
      queryClient.setQueryData(keys.agent(saved.id), saved);
      toast.success(agent ? "Agent saved" : "Agent created", saved.name);
      onClose();
    },
  });

  const errors = fieldErrorsOf(save.error);
  const rowFields = rows.flatMap((_, i) => [`variables.${i}`, `variables.${i}.name`, `variables.${i}.allowed`]);

  return (
    <Modal
      wide
      title={agent ? `Edit ${agent.name}` : "New agent"}
      description="The variables define the columns of the cohort CSV. Every contact row must supply the required ones."
      onClose={onClose}
      onSubmit={() => save.mutate()}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="primary" loading={save.isPending}>
            {agent ? "Save agent" : "Create agent"}
          </Button>
        </>
      }
    >
      <div className="stack">
        {save.isError && <ErrorBanner error={save.error} shownFields={[...BASE_FIELDS, ...rowFields]} />}
        <div className="form-grid">
          <Field label="Name" error={errors.name}>
            <input className="input" value={name} onChange={(e) => setName(e.target.value)} autoFocus />
          </Field>
          <div className="grid-2" style={{ gap: 12 }}>
            <Field label="App ID" error={errors.app_id}>
              <input className="input mono" value={appId} onChange={(e) => setAppId(e.target.value)} />
            </Field>
            <Field label="App version" error={errors.app_version}>
              <input
                className="input"
                type="number"
                min={1}
                step={1}
                value={appVersion}
                onChange={(e) => setAppVersion(e.target.value)}
              />
            </Field>
          </div>
          <Field
            label="Initial bot message"
            optional
            className="span-2"
            hint="Use {variable_name} to insert a contact's values."
            error={errors.initial_bot_message}
          >
            <textarea
              className="textarea"
              rows={2}
              style={{ minHeight: 60 }}
              value={greeting}
              onChange={(e) => setGreeting(e.target.value)}
            />
          </Field>
          <Field label="Initial state name" optional error={errors.initial_state_name}>
            <input className="input mono" value={stateName} onChange={(e) => setStateName(e.target.value)} />
          </Field>
        </div>

        <div>
          <div className="row" style={{ marginBottom: 8 }}>
            <div>
              <div className="section-title" style={{ marginBottom: 0 }}>
                Variables
              </div>
              <p className="muted small">
                Lowercase letters, digits and underscores. <span className="mono">phone_number</span> and{" "}
                <span className="mono">lead_id</span> are always included.
              </p>
            </div>
            <div className="spacer" />
            <Button size="sm" icon={<Plus size={14} />} onClick={addRow}>
              Add variable
            </Button>
          </div>
          {errors.variables && <p className="field__error" style={{ marginBottom: 8 }}>{errors.variables}</p>}
          {rows.length === 0 ? (
            <div className="fieldset muted small" style={{ textAlign: "center" }}>
              No variables. Contacts will only need a phone number.
            </div>
          ) : (
            <div className="fieldset" style={{ padding: 0, overflow: "hidden" }}>
              <table className="table table--compact var-table">
                <thead>
                  <tr>
                    <th style={{ width: "24%" }}>Name</th>
                    <th style={{ width: "15%" }}>Type</th>
                    <th style={{ width: "9%" }}>Required</th>
                    <th style={{ width: "22%" }}>Example</th>
                    <th>Allowed values</th>
                    <th style={{ width: 40 }} />
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r, i) => {
                    const nameError = errors[`variables.${i}.name`];
                    const rowError = errors[`variables.${i}`] ?? errors[`variables.${i}.allowed`];
                    return (
                      <Fragment key={r.key}>
                        <tr>
                          <td>
                            <input
                              className="input input--sm mono"
                              placeholder="customer_name"
                              aria-label="Variable name"
                              aria-invalid={nameError ? true : undefined}
                              value={r.name}
                              onChange={(e) => update(r.key, { name: e.target.value })}
                            />
                          </td>
                          <td>
                            <select
                              className="select select--sm"
                              aria-label="Type"
                              value={r.type}
                              onChange={(e) => update(r.key, { type: e.target.value as VariableType })}
                            >
                              {VARIABLE_TYPES.map((t) => (
                                <option key={t} value={t}>
                                  {t}
                                </option>
                              ))}
                            </select>
                          </td>
                          <td style={{ textAlign: "center" }}>
                            <input
                              type="checkbox"
                              className="check-input"
                              aria-label="Required"
                              checked={r.required}
                              onChange={(e) => update(r.key, { required: e.target.checked })}
                            />
                          </td>
                          <td>
                            <input
                              className="input input--sm"
                              aria-label="Example"
                              placeholder={EXAMPLE_HINT[r.type]}
                              value={r.example}
                              onChange={(e) => update(r.key, { example: e.target.value })}
                            />
                          </td>
                          <td>
                            {r.type === "enum" ? (
                              <input
                                className="input input--sm"
                                aria-label="Allowed values"
                                placeholder="en, hi, ta"
                                aria-invalid={rowError ? true : undefined}
                                value={r.allowed}
                                onChange={(e) => update(r.key, { allowed: e.target.value })}
                              />
                            ) : (
                              <span className="faint small">Any {r.type}</span>
                            )}
                          </td>
                          <td>
                            <Button
                              size="sm"
                              variant="ghost"
                              aria-label={`Remove ${r.name || "variable"}`}
                              icon={<Trash2 size={14} />}
                              onClick={() => setRows((all) => all.filter((x) => x.key !== r.key))}
                            />
                          </td>
                        </tr>
                        {(nameError || rowError) && (
                          <tr className="var-table__error">
                            <td colSpan={6}>
                              <span className="field__error">{nameError ?? rowError}</span>
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </Modal>
  );
}

const EXAMPLE_HINT: Record<VariableType, string> = {
  string: "Priya",
  number: "4500.50",
  integer: "3",
  boolean: "true",
  date: "2026-11-05",
  enum: "en",
};
