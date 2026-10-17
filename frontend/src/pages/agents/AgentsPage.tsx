import { useState } from "react";
import { Bot, Pencil, Plus } from "lucide-react";
import { useAgents } from "../../api/queries";
import type { Agent, Workspace } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { Button } from "../../components/Button";
import { EmptyState, QueryError, SkeletonRows } from "../../components/Feedback";
import { PageHeader } from "../../components/PageHeader";
import { RequireWorkspace } from "../../layout/RequireWorkspace";
import { formatDateTime } from "../../lib/format";
import { AgentModal } from "./AgentModal";
import { SampleCsvButton } from "./SampleCsvButton";

export function AgentsPage() {
  return <RequireWorkspace>{(ws) => <Agents workspace={ws} />}</RequireWorkspace>;
}

function Agents({ workspace }: { workspace: Workspace }) {
  const { isAdmin } = useAuth();
  const agents = useAgents(workspace.id);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<Agent | null>(null);

  const newButton = isAdmin && (
    <Button variant="primary" icon={<Plus size={16} />} onClick={() => setCreating(true)}>
      New agent
    </Button>
  );

  return (
    <>
      <PageHeader
        title="Agents"
        description="Voice agents and the variables each one needs per contact. A cohort CSV has one column per variable."
        actions={newButton}
      />
      <div className="card">
        {agents.isError ? (
          <QueryError error={agents.error} onRetry={() => agents.refetch()} />
        ) : agents.data?.length === 0 ? (
          <EmptyState icon={<Bot size={20} />} title="No agents yet" action={newButton}>
            {isAdmin
              ? "Register a Sarvam app as an agent and describe the variables it expects."
              : "An admin needs to add an agent before campaigns can be created."}
          </EmptyState>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>App</th>
                  <th>Variables</th>
                  <th>Created</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {agents.isPending ? (
                  <SkeletonRows cols={5} rows={3} />
                ) : (
                  agents.data.map((a) => (
                    <tr key={a.id}>
                      <td>
                        <div className="cell-title">{a.name}</div>
                        {a.initial_bot_message && (
                          <div className="cell-sub" style={{ maxWidth: 320 }} title={a.initial_bot_message}>
                            "{truncate(a.initial_bot_message, 60)}"
                          </div>
                        )}
                      </td>
                      <td className="nowrap">
                        <span className="mono">{a.app_id}</span>
                        <span className="muted"> · v{a.app_version}</span>
                      </td>
                      <td>
                        {a.variables.length === 0 ? (
                          <span className="faint">None</span>
                        ) : (
                          <div className="chip-list">
                            {a.variables.map((v) => (
                              <span key={v.name} className="chip" title={v.required ? "Required" : "Optional"}>
                                <span className="mono">{v.name}</span>
                                <span className="faint">
                                  {v.type}
                                  {v.required ? "" : "?"}
                                </span>
                              </span>
                            ))}
                          </div>
                        )}
                      </td>
                      <td className="muted nowrap">{formatDateTime(a.created_at)}</td>
                      <td className="num nowrap">
                        <div className="row" style={{ justifyContent: "flex-end" }}>
                          <SampleCsvButton agent={a} />
                          {isAdmin && (
                            <Button
                              size="sm"
                              variant="ghost"
                              icon={<Pencil size={14} />}
                              onClick={() => setEditing(a)}
                            >
                              Edit
                            </Button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>
      {creating && <AgentModal workspaceId={workspace.id} onClose={() => setCreating(false)} />}
      {editing && <AgentModal workspaceId={workspace.id} agent={editing} onClose={() => setEditing(null)} />}
    </>
  );
}

function truncate(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}
