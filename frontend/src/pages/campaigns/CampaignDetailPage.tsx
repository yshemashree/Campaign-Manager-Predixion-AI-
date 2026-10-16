import { lazy, Suspense, useEffect, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Copy, Download, Pause, Play, Settings2, Square, Trash2 } from "lucide-react";
import { campaignApi } from "../../api/endpoints";
import { keys, useAgent, useCampaign, useConnections, useOrganization } from "../../api/queries";
import type { Campaign, CampaignStats, Contact, LifecycleAction } from "../../api/types";
import { Button } from "../../components/Button";
import { Banner, PageSpinner, QueryError } from "../../components/Feedback";
import { Menu, type MenuItem } from "../../components/Menu";
import { ConfirmDialog } from "../../components/Overlay";
import { RelativeTime } from "../../components/RelativeTime";
import { StatusPill } from "../../components/StatusPill";
import { useToast } from "../../components/Toast";
import { saveFile } from "../../lib/download";
import { formatDateTime, formatNumber, formatZoneDayTime } from "../../lib/format";
import { useWorkspace } from "../../workspace/WorkspaceContext";
import { CampaignSummary } from "./CampaignSummary";
import { CohortsSection, UploadContactsModal } from "./detail/Cohorts";
import { ContactDrawer } from "./detail/ContactDrawer";
import { ContactsTable } from "./detail/ContactsTable";
import { EditSettingsModal } from "./detail/EditSettingsModal";
import { LiveStats } from "./detail/LiveStats";
import { useCampaignLive } from "./detail/useCampaignLive";
import "./detail/detail.css";

// Recharts is large; load it only when a campaign is opened.
const RateChart = lazy(() => import("./detail/RateChart").then((m) => ({ default: m.RateChart })));

const EDITABLE = new Set(["draft", "scheduled", "paused", "running"]);

const PAUSE_REASONS: Record<string, string> = {
  missing_credentials:
    "Paused automatically: this workspace has no Sarvam API key. Add one under Workspaces, then resume.",
  auth_error: "Paused automatically: Sarvam rejected the workspace's API key. Update the key under Workspaces, then resume.",
  config_error:
    "Paused automatically: Sarvam rejected the call requests. Check the agent's app ID and version and the connection, then resume.",
};

const ACTION_LABEL: Record<LifecycleAction, { done: string; failed: string }> = {
  start: { done: "Campaign started", failed: "Couldn't start the campaign" },
  pause: { done: "Campaign paused", failed: "Couldn't pause the campaign" },
  resume: { done: "Campaign resumed", failed: "Couldn't resume the campaign" },
  stop: { done: "Campaign stopped", failed: "Couldn't stop the campaign" },
};

export function CampaignDetailPage() {
  const { campaignId = "" } = useParams();
  const campaign = useCampaign(campaignId);

  if (campaign.isPending) return <PageSpinner />;
  if (campaign.isError) {
    return (
      <div className="card">
        <QueryError error={campaign.error} onRetry={() => campaign.refetch()} />
      </div>
    );
  }
  return <CampaignDetail campaign={campaign.data} />;
}

type Tab = "contacts" | "uploads" | "settings";

function CampaignDetail({ campaign }: { campaign: Campaign }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const toast = useToast();
  const { workspaces, workspaceId, setWorkspaceId } = useWorkspace();
  const { stats, mode, flash } = useCampaignLive(campaign.id);
  const agent = useAgent(campaign.agent_id);
  const connections = useConnections(campaign.workspace_id);
  const connection = connections.data?.find((c) => c.id === campaign.connection_id);

  // CampaignOut has no org id; get it from the user, or from the workspace for superadmins.
  const orgId = campaign.org_id;
  const org = useOrganization(orgId);

  const [tab, setTab] = useState<Tab>("contacts");
  const [selected, setSelected] = useState<Contact | null>(null);
  const [confirm, setConfirm] = useState<"stop" | "delete" | null>(null);
  const [editing, setEditing] = useState(false);
  const [uploading, setUploading] = useState(false);

  // Opening a campaign from a link should also switch the header to its workspace.
  useEffect(() => {
    if (workspaceId && campaign.workspace_id !== workspaceId && workspaces.some((w) => w.id === campaign.workspace_id)) {
      setWorkspaceId(campaign.workspace_id);
    }
  }, [campaign.workspace_id, workspaceId, workspaces, setWorkspaceId]);

  const lifecycle = useMutation({
    mutationFn: (action: LifecycleAction) => campaignApi.setStatus(campaign.id, action),
    onSuccess: (updated, action) => {
      queryClient.setQueryData(keys.campaign(campaign.id), updated);
      queryClient.invalidateQueries({ queryKey: keys.stats(campaign.id), exact: true });
      queryClient.invalidateQueries({ queryKey: ["campaigns"] });
      const scheduled = action !== "pause" && action !== "stop" && updated.status === "scheduled";
      toast.success(
        scheduled ? "Campaign scheduled" : ACTION_LABEL[action].done,
        scheduled && updated.start_at ? `Calls begin ${formatDateTime(updated.start_at)}.` : undefined,
      );
      setConfirm(null);
    },
    onError: (err, action) => {
      toast.apiError(ACTION_LABEL[action].failed, err);
      setConfirm(null);
    },
  });

  const remove = useMutation({
    mutationFn: () => campaignApi.remove(campaign.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["campaigns"] });
      toast.success("Draft deleted", campaign.name);
      navigate("/campaigns", { replace: true });
    },
    onError: (err) => {
      toast.apiError("Couldn't delete the draft", err);
      setConfirm(null);
    },
  });

  const duplicate = useMutation({
    mutationFn: () => campaignApi.duplicate(campaign.id),
    onSuccess: (copy) => {
      queryClient.invalidateQueries({ queryKey: ["campaigns"] });
      toast.success("Campaign duplicated", `${copy.name} is a new draft.`);
      navigate(`/campaigns/${copy.id}`);
    },
    onError: (err) => toast.apiError("Couldn't duplicate the campaign", err),
  });

  const [exporting, setExporting] = useState(false);
  async function exportResults() {
    setExporting(true);
    try {
      const { blob, filename } = await campaignApi.exportCsv(campaign.id);
      saveFile(blob, filename ?? `${campaign.name}-results.csv`);
    } catch (err) {
      toast.apiError("Couldn't export the results", err);
    } finally {
      setExporting(false);
    }
  }

  const moreActions: MenuItem[] = [
    { label: "Duplicate as draft", icon: <Copy size={14} />, onSelect: () => duplicate.mutate() },
    ...(campaign.status === "draft"
      ? [{ label: "Delete draft", icon: <Trash2 size={14} />, danger: true, onSelect: () => setConfirm("delete") }]
      : []),
  ];

  const status = campaign.status;
  const windowClosed =
    (status === "running" || status === "scheduled") && stats.data && !stats.data.in_window;
  const pending = lifecycle.isPending ? lifecycle.variables : null;
  const total = stats.data?.total ?? 0;
  const pausedAuto = status === "paused" && campaign.pause_reason && campaign.pause_reason !== "user";

  return (
    <>
      <div className="detail-header">
        <Link to="/campaigns" className="back-link">
          <ArrowLeft size={14} /> Outbound Campaigns
        </Link>
        <div className="detail-header__row">
          <div className="detail-header__title">
            <h1>{campaign.name}</h1>
            <StatusPill status={status} kind="campaign" />
          </div>
          <div className="page-header__actions">
            <Button icon={<Download size={15} />} loading={exporting} onClick={exportResults}>
              Export results
            </Button>
            {EDITABLE.has(status) && (
              <Button icon={<Settings2 size={15} />} onClick={() => setEditing(true)}>
                Edit settings
              </Button>
            )}
            {(status === "running" || status === "scheduled") && (
              <Button
                icon={<Pause size={15} />}
                loading={pending === "pause"}
                disabled={lifecycle.isPending}
                onClick={() => lifecycle.mutate("pause")}
              >
                Pause
              </Button>
            )}
            {(status === "running" || status === "scheduled" || status === "paused") && (
              <Button
                variant="danger-outline"
                icon={<Square size={14} />}
                disabled={lifecycle.isPending}
                onClick={() => setConfirm("stop")}
              >
                Stop
              </Button>
            )}
            {status === "paused" && (
              <Button
                variant="primary"
                icon={<Play size={15} />}
                loading={pending === "resume"}
                disabled={lifecycle.isPending}
                onClick={() => lifecycle.mutate("resume")}
              >
                Resume
              </Button>
            )}
            {status === "draft" && (
              <Button
                variant="primary"
                icon={<Play size={15} />}
                loading={pending === "start"}
                disabled={lifecycle.isPending || (stats.data !== undefined && total === 0)}
                title={stats.data !== undefined && total === 0 ? "Upload contacts before starting" : undefined}
                onClick={() => lifecycle.mutate("start")}
              >
                Start
              </Button>
            )}
            <Menu label="More campaign actions" items={moreActions} />
          </div>
        </div>
        <HeaderFacts campaign={campaign} agentName={agent.data?.name} connectionName={connection?.name} stats={stats.data} />
      </div>

      <div className="stack" style={{ gap: 20 }}>
        {windowClosed && (
          <Banner tone="info" title="Calling window closed">
            {stats.data?.next_window_opens_at ? (
              <>
                No calls are placed until it opens again on{" "}
                {formatZoneDayTime(stats.data.next_window_opens_at, campaign.calling_window.timezone)},{" "}
                <RelativeTime iso={stats.data.next_window_opens_at} />
              </>
            ) : (
              "There is no calling window left before the campaign's end time."
            )}
          </Banner>
        )}
        {pausedAuto && (
          <Banner tone="error" title="Campaign paused">
            {PAUSE_REASONS[campaign.pause_reason!] ?? `Paused automatically (${campaign.pause_reason}).`}
          </Banner>
        )}
        {status === "paused" && campaign.pause_reason === "user" && (
          <Banner tone="warning" title="Paused">
            No new calls are being placed. Calls already in progress finish normally. Resume to carry on.
          </Banner>
        )}
        {status === "draft" && stats.data && total === 0 && (
          <Banner tone="info" title="Add contacts to start this campaign">
            Upload a CSV of the people to call.{" "}
            <button className="link-btn" onClick={() => setUploading(true)}>
              Upload contacts
            </button>
          </Banner>
        )}

        <LiveStats campaign={campaign} stats={stats.data} mode={mode} />
        <Suspense fallback={<div className="card" style={{ height: 290 }} />}>
          <RateChart orgId={orgId} orgName={org.data?.name} />
        </Suspense>

        <div className="card">
          <div className="tabs" role="tablist">
            <TabButton id="contacts" current={tab} onSelect={setTab}>
              Contacts {stats.data && <span className="tabs__count">{formatNumber(total)}</span>}
            </TabButton>
            <TabButton id="uploads" current={tab} onSelect={setTab}>
              Uploads
            </TabButton>
            <TabButton id="settings" current={tab} onSelect={setTab}>
              Settings
            </TabButton>
          </div>
          {tab === "contacts" && (
            <ContactsTable
              campaignId={campaign.id}
              stats={stats.data}
              flash={flash}
              selectedId={selected?.id ?? null}
              onSelect={setSelected}
              pollMs={mode === "live" || !["running", "scheduled", "paused"].includes(status) ? false : 5000}
            />
          )}
          {tab === "uploads" && <CohortsSection campaign={campaign} onUpload={() => setUploading(true)} />}
          {tab === "settings" && (
            <div className="card__body">
              <CampaignSummary
                settings={campaign}
                agent={agent.data}
                connection={connection}
              />
              {EDITABLE.has(status) && (
                <div style={{ marginTop: 16 }}>
                  <Button icon={<Settings2 size={15} />} onClick={() => setEditing(true)}>
                    Edit settings
                  </Button>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {selected && <ContactDrawer contact={selected} onClose={() => setSelected(null)} />}
      {uploading && <UploadContactsModal campaign={campaign} agent={agent.data} onClose={() => setUploading(false)} />}
      {editing && (
        <EditSettingsModal
          campaign={campaign}
          connection={connection}
          orgCps={org.data?.max_calls_per_second}
          pausing={pending === "pause"}
          onPause={() => lifecycle.mutate("pause")}
          onClose={() => setEditing(false)}
        />
      )}
      {confirm === "stop" && (
        <ConfirmDialog
          title="Stop this campaign?"
          confirmLabel="Stop campaign"
          danger
          loading={lifecycle.isPending}
          onConfirm={() => lifecycle.mutate("stop")}
          onClose={() => setConfirm(null)}
        >
          <p>No new calls will be placed. Calls already in progress finish normally.</p>
          <p>
            Contacts still waiting
            {stats.data
              ? ` (${formatNumber((stats.data.by_status.pending ?? 0) + (stats.data.by_status.retry_scheduled ?? 0))})`
              : ""}{" "}
            are cancelled. A stopped campaign can't be restarted.
          </p>
        </ConfirmDialog>
      )}
      {confirm === "delete" && (
        <ConfirmDialog
          title="Delete this draft?"
          confirmLabel="Delete draft"
          danger
          loading={remove.isPending}
          onConfirm={() => remove.mutate()}
          onClose={() => setConfirm(null)}
        >
          <p>The campaign and any contacts uploaded to it are deleted. This can't be undone.</p>
        </ConfirmDialog>
      )}
    </>
  );
}

function TabButton({
  id,
  current,
  onSelect,
  children,
}: {
  id: Tab;
  current: Tab;
  onSelect: (tab: Tab) => void;
  children: ReactNode;
}) {
  return (
    <button role="tab" aria-selected={current === id} className={current === id ? "is-active" : ""} onClick={() => onSelect(id)}>
      {children}
    </button>
  );
}

function HeaderFacts({
  campaign,
  agentName,
  connectionName,
  stats,
}: {
  campaign: Campaign;
  agentName?: string;
  connectionName?: string;
  stats?: CampaignStats;
}) {
  const cw = campaign.calling_window;
  const facts = [
    agentName && `Agent: ${agentName}`,
    connectionName && `Connection: ${connectionName}`,
    `${campaign.attempts_per_second} attempts/s`,
    `${cw.start}–${cw.end} ${cw.timezone.replace(/_/g, " ")}`,
    campaign.status === "scheduled" && campaign.start_at && `Starts ${formatDateTime(campaign.start_at)}`,
    campaign.end_at && `Ends ${formatDateTime(campaign.end_at)}`,
    stats && stats.total === 0 && "No contacts yet",
  ].filter(Boolean);
  return (
    <div className="detail-header__facts">
      {facts.map((f) => (
        <span key={String(f)}>{f}</span>
      ))}
    </div>
  );
}
