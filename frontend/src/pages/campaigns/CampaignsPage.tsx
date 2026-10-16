import { useMemo } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Bot, Check, Copy, ExternalLink, Megaphone, PhoneCall, Plus, Search } from "lucide-react";
import { campaignApi } from "../../api/endpoints";
import { keys, useAgents, useCampaigns, useConnections } from "../../api/queries";
import type { Campaign, CampaignStatus, Workspace } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { QueryError, SkeletonRows } from "../../components/Feedback";
import { Menu } from "../../components/Menu";
import { PageHeader } from "../../components/PageHeader";
import { ProgressBar } from "../../components/ProgressBar";
import { RelativeTime } from "../../components/RelativeTime";
import { StatusPill } from "../../components/StatusPill";
import { useToast } from "../../components/Toast";
import { RequireWorkspace } from "../../layout/RequireWorkspace";
import { count, segments, totalCount } from "../../lib/contactStatus";
import { formatNumber } from "../../lib/format";

const FILTERS: { id: string; label: string; statuses: CampaignStatus[] | null }[] = [
  { id: "all", label: "All", statuses: null },
  { id: "active", label: "Active", statuses: ["running", "scheduled", "paused"] },
  { id: "draft", label: "Drafts", statuses: ["draft"] },
  { id: "done", label: "Finished", statuses: ["completed", "stopped"] },
];

export function CampaignsPage() {
  return <RequireWorkspace>{(ws) => <Campaigns workspace={ws} />}</RequireWorkspace>;
}

function Campaigns({ workspace }: { workspace: Workspace }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const toast = useToast();
  const campaigns = useCampaigns(workspace.id);
  const agents = useAgents(workspace.id);
  const connections = useConnections(workspace.id);

  // Filters live in the URL so a filtered list can be bookmarked or shared.
  const [params, setParams] = useSearchParams();
  const filter = FILTERS.some((f) => f.id === params.get("status")) ? params.get("status")! : "all";
  const search = params.get("q") ?? "";
  const setParam = (key: string, value: string, fallback: string) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (!value || value === fallback) next.delete(key);
        else next.set(key, value);
        return next;
      },
      { replace: true },
    );

  const duplicate = useMutation({
    mutationFn: (c: Campaign) => campaignApi.duplicate(c.id),
    onSuccess: (copy) => {
      queryClient.invalidateQueries({ queryKey: keys.campaigns(workspace.id) });
      toast.success("Campaign duplicated", `${copy.name} is a new draft.`);
      navigate(`/campaigns/${copy.id}`);
    },
    onError: (err) => toast.apiError("Couldn't duplicate the campaign", err),
  });

  const agentNames = new Map(agents.data?.map((a) => [a.id, a.name]));
  const connectionNames = new Map(connections.data?.map((c) => [c.id, c.name]));

  const visible = useMemo(() => {
    const statuses = FILTERS.find((f) => f.id === filter)?.statuses;
    const term = search.trim().toLowerCase();
    return (campaigns.data ?? []).filter(
      (c) => (!statuses || statuses.includes(c.status)) && (!term || c.name.toLowerCase().includes(term)),
    );
  }, [campaigns.data, filter, search]);

  const counts = useMemo(() => {
    const out: Record<string, number> = {};
    for (const f of FILTERS) {
      out[f.id] = (campaigns.data ?? []).filter((c) => !f.statuses || f.statuses.includes(c.status)).length;
    }
    return out;
  }, [campaigns.data]);

  const newButton = (
    <Link to="/campaigns/new" className="btn btn--primary">
      <Plus size={16} /> New campaign
    </Link>
  );

  if (campaigns.data?.length === 0 && !agents.isPending && !connections.isPending) {
    return (
      <>
        <PageHeader title="Outbound Campaigns" description={`Calling campaigns in ${workspace.name}.`} />
        <GettingStarted hasAgent={(agents.data?.length ?? 0) > 0} hasConnection={(connections.data?.length ?? 0) > 0} />
      </>
    );
  }

  return (
    <>
      <PageHeader title="Outbound Campaigns" description={`Calling campaigns in ${workspace.name}.`} actions={newButton} />

      <div className="card">
        <div className="toolbar">
          <div className="segmented" role="tablist" aria-label="Filter campaigns">
            {FILTERS.map((f) => (
              <button
                key={f.id}
                role="tab"
                aria-selected={filter === f.id}
                className={filter === f.id ? "is-active" : ""}
                onClick={() => setParam("status", f.id, "all")}
              >
                {f.label}
                <span className="segmented__count">{counts[f.id] ?? 0}</span>
              </button>
            ))}
          </div>
          <div className="spacer" />
          <div className="search">
            <Search size={15} />
            <input
              className="input input--sm"
              placeholder="Search by name"
              value={search}
              onChange={(e) => setParam("q", e.target.value, "")}
              aria-label="Search campaigns"
            />
          </div>
        </div>

        {campaigns.isError ? (
          <QueryError error={campaigns.error} onRetry={() => campaigns.refetch()} />
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th style={{ minWidth: 240 }}>Name</th>
                  <th>Status</th>
                  <th style={{ width: 200, minWidth: 180 }}>Progress</th>
                  <th className="num">Attempts / sec</th>
                  <th>Created</th>
                  <th style={{ width: 48 }}>
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {campaigns.isPending ? (
                  <SkeletonRows cols={6} rows={4} />
                ) : visible.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="muted" style={{ textAlign: "center", padding: 32 }}>
                      No campaigns match this filter.
                    </td>
                  </tr>
                ) : (
                  visible.map((c) => (
                    <CampaignRow
                      key={c.id}
                      campaign={c}
                      subtitle={[agentNames.get(c.agent_id), connectionNames.get(c.connection_id)].filter(Boolean).join(" · ")}
                      onOpen={() => navigate(`/campaigns/${c.id}`)}
                      onDuplicate={() => duplicate.mutate(c)}
                    />
                  ))
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}

function CampaignRow({
  campaign,
  subtitle,
  onOpen,
  onDuplicate,
}: {
  campaign: Campaign;
  subtitle: string;
  onOpen: () => void;
  onDuplicate: () => void;
}) {
  const total = totalCount(campaign.contact_counts);
  const completed = count(campaign.contact_counts, "completed");
  return (
    <tr className="clickable" onClick={onOpen}>
      <td>
        <Link to={`/campaigns/${campaign.id}`} className="cell-title" onClick={(e) => e.stopPropagation()}>
          {campaign.name}
        </Link>
        {subtitle && <div className="cell-sub">{subtitle}</div>}
      </td>
      <td>
        <StatusPill status={campaign.status} kind="campaign" />
        {campaign.status === "paused" && campaign.pause_reason && campaign.pause_reason !== "user" && (
          <div className="cell-sub error-text">Auto-paused</div>
        )}
      </td>
      <td>
        <div className="stack-sm" style={{ gap: 6 }}>
          <span className="small tabular">
            <strong>{formatNumber(completed)}</strong>
            <span className="muted"> / {formatNumber(total)} completed</span>
          </span>
          <ProgressBar segments={segments(campaign.contact_counts)} total={total} thin />
        </div>
      </td>
      <td className="num">{campaign.attempts_per_second}</td>
      <td className="muted nowrap">
        <RelativeTime iso={campaign.created_at} />
      </td>
      <td className="num">
        <Menu
          label={`Actions for ${campaign.name}`}
          items={[
            { label: "Open", icon: <ExternalLink size={14} />, onSelect: onOpen },
            { label: "Duplicate", icon: <Copy size={14} />, onSelect: onDuplicate },
          ]}
        />
      </td>
    </tr>
  );
}

/** First-run guide: a campaign needs an agent and a connection, in that order. */
function GettingStarted({ hasAgent, hasConnection }: { hasAgent: boolean; hasConnection: boolean }) {
  const { isAdmin } = useAuth();
  const steps = [
    {
      done: hasAgent,
      icon: <Bot size={18} />,
      title: "Add an agent",
      text: "Register the Sarvam app that makes the calls, and the variables it needs for each contact.",
      action: isAdmin ? { to: "/agents", label: "Add agent" } : null,
    },
    {
      done: hasConnection,
      icon: <PhoneCall size={18} />,
      title: "Add a connection",
      text: "The telephony connection and the caller numbers calls go out from.",
      action: isAdmin ? { to: "/connections", label: "Add connection" } : null,
    },
    {
      done: false,
      icon: <Megaphone size={18} />,
      title: "Create your first campaign",
      text: "Pick the agent, upload recipients as a CSV, set a schedule and launch.",
      action: hasAgent && hasConnection ? { to: "/campaigns/new", label: "New campaign" } : null,
    },
  ];
  const current = steps.findIndex((s) => !s.done);
  return (
    <div className="card onboarding">
      <div className="card__header">
        <div>
          <h2>Get this workspace calling</h2>
          <p>Three steps, in this order.{!isAdmin && " Agents and connections are added by an admin."}</p>
        </div>
      </div>
      <ol className="onboarding__steps">
        {steps.map((s, i) => (
          <li key={s.title} className={s.done ? "is-done" : i === current ? "is-current" : ""}>
            <span className="onboarding__icon">{s.done ? <Check size={18} /> : s.icon}</span>
            <div className="onboarding__text">
              <strong>
                {i + 1}. {s.title}
              </strong>
              <p>{s.text}</p>
            </div>
            {s.done ? (
              <span className="pill pill--green">Done</span>
            ) : (
              s.action && (
                <Link to={s.action.to} className={`btn ${i === current ? "btn--primary" : ""}`}>
                  {s.action.label}
                </Link>
              )
            )}
          </li>
        ))}
      </ol>
    </div>
  );
}
