import { useRef, useState, type ReactNode } from "react";
import { Link, useNavigate } from "react-router";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Check, Rocket } from "lucide-react";
import { ApiError } from "../../api/client";
import { agentApi, campaignApi, cohortApi } from "../../api/endpoints";
import { keys, useAgents, useConnections, useOrganization } from "../../api/queries";
import type { Campaign, Workspace } from "../../api/types";
import { Button } from "../../components/Button";
import { Banner, ErrorBanner, PageSpinner } from "../../components/Feedback";
import { Field } from "../../components/Field";
import { PageHeader } from "../../components/PageHeader";
import { useToast } from "../../components/Toast";
import { RequireWorkspace } from "../../layout/RequireWorkspace";
import { formatDateTime, formatNumber } from "../../lib/format";
import { CohortUploader, EMPTY_COHORT, cohortReady, importableRows, type CohortDraft } from "./CohortUploader";
import { CampaignSummary } from "./CampaignSummary";
import {
  CallerNumbersField,
  OverridesFields,
  PacingFields,
  RetryFields,
  ScheduleFields,
  SETTINGS_FIELDS,
} from "./SettingsFields";
import {
  defaultForm,
  stepForField,
  toSettings,
  validateBasics,
  validatePacing,
  validateSchedule,
  type CampaignForm,
  type FormErrors,
} from "./settingsForm";
import "./wizard.css";

const STEPS = [
  { id: "agent", label: "Agent" },
  { id: "recipients", label: "Recipients" },
  { id: "schedule", label: "Schedule" },
  { id: "review", label: "Review & Launch" },
] as const;
type StepId = (typeof STEPS)[number]["id"];

export function NewCampaignPage() {
  return <RequireWorkspace>{(ws) => <Wizard key={ws.id} workspace={ws} />}</RequireWorkspace>;
}

function Wizard({ workspace }: { workspace: Workspace }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const toast = useToast();
  const agents = useAgents(workspace.id);
  const connections = useConnections(workspace.id);
  const org = useOrganization(workspace.org_id);

  const [step, setStep] = useState<StepId>("agent");
  const [form, setForm] = useState<CampaignForm>(defaultForm);
  const [errors, setErrors] = useState<FormErrors>({});
  const [serverError, setServerError] = useState<unknown>(null);
  const [cohort, setCohort] = useState<CohortDraft>(EMPTY_COHORT);
  const [submitting, setSubmitting] = useState<"launch" | "draft" | null>(null);
  // Set once the campaign exists, so retrying after a failed upload doesn't create a second one.
  const created = useRef<Campaign | null>(null);

  const agent = agents.data?.find((a) => a.id === form.agentId);
  const connection = connections.data?.find((c) => c.id === form.connectionId);
  const stepIndex = STEPS.findIndex((s) => s.id === step);

  function validate(id: StepId, values: CampaignForm = form): FormErrors {
    if (id === "agent") return validateBasics(values);
    if (id === "schedule") return { ...validateSchedule(values), ...validatePacing(values) };
    return {};
  }

  const set = (patch: Partial<CampaignForm>) => {
    // A different agent means a different CSV layout: the checked file no longer applies.
    if (patch.agentId !== undefined && patch.agentId !== form.agentId) setCohort(EMPTY_COHORT);
    const next = { ...form, ...patch };
    if (patch.connectionId !== undefined && patch.connectionId !== form.connectionId) {
      next.allNumbers = true;
      next.callerNumbers = [];
    }
    setForm(next);
    if (Object.keys(errors).length > 0) setErrors(validate(step, next));
  };

  function goTo(id: StepId) {
    const target = STEPS.findIndex((s) => s.id === id);
    if (target <= stepIndex) {
      setStep(id);
      return;
    }
    // Moving forward validates each step on the way.
    for (const s of STEPS.slice(0, target)) {
      const found = validate(s.id);
      if (Object.keys(found).length > 0) {
        setErrors(found);
        setStep(s.id);
        return;
      }
      if (s.id === "recipients" && cohort.file && !cohortReady(cohort)) {
        setStep("recipients");
        return;
      }
    }
    setErrors({});
    setServerError(null);
    setStep(id);
  }

  async function finish(launch: boolean) {
    setSubmitting(launch ? "launch" : "draft");
    setServerError(null);
    try {
      const settings = toSettings(form);
      let campaign = created.current
        ? await campaignApi.update(created.current.id, settings)
        : await campaignApi.create(workspace.id, { ...settings, agent_id: form.agentId, connection_id: form.connectionId });
      created.current = campaign;

      if (cohort.file && cohortReady(cohort) && !cohort.check?.cohort) {
        const upload = await cohortApi.upload(campaign.id, cohort.file, { dryRun: false, skipInvalid: cohort.skipInvalid });
        if (!upload.accepted) {
          setCohort({ ...cohort, check: upload });
          setStep("recipients");
          toast.error("The contacts weren't imported", "The campaign is saved as a draft. Review the problems below.");
          return;
        }
        // Remember the import so a retry doesn't upload the same file twice.
        setCohort((c) => ({ ...c, check: upload }));
      }

      if (launch) campaign = await campaignApi.setStatus(campaign.id, "start");
      queryClient.setQueryData(keys.campaign(campaign.id), campaign);
      queryClient.invalidateQueries({ queryKey: keys.campaigns(workspace.id) });
      toast.success(
        !launch ? "Saved as draft" : campaign.status === "scheduled" ? "Campaign scheduled" : "Campaign launched",
        campaign.status === "scheduled" && campaign.start_at
          ? `Calls begin ${formatDateTime(campaign.start_at)}.`
          : campaign.name,
      );
      navigate(`/campaigns/${campaign.id}`);
    } catch (err) {
      setServerError(err);
      if (err instanceof ApiError && err.errors.length > 0) {
        setErrors(err.fieldErrors());
        setStep(stepForField(err.errors[0].field));
      }
    } finally {
      setSubmitting(null);
    }
  }

  if (agents.isPending || connections.isPending) return <PageSpinner />;

  const header = (
    <PageHeader
      title="New outbound campaign"
      description={`In ${workspace.name}. Nothing is called until you launch.`}
      actions={<Button onClick={() => navigate("/campaigns")}>Cancel</Button>}
    >
      <Link to="/campaigns" className="back-link">
        <ArrowLeft size={14} /> Outbound Campaigns
      </Link>
    </PageHeader>
  );

  const noAgents = (agents.data?.length ?? 0) === 0;
  const noConnections = (connections.data?.length ?? 0) === 0;
  if (noAgents || noConnections) {
    return (
      <>
        {header}
        <Banner tone="warning" title="This workspace isn't ready for campaigns yet">
          A campaign needs an agent and a connection. {noAgents && <Link to="/agents">Add an agent</Link>}
          {noAgents && noConnections && " and "}
          {noConnections && <Link to="/connections">add a connection</Link>}.
        </Banner>
      </>
    );
  }

  const importCount = cohort.check && cohortReady(cohort) ? importableRows(cohort.check) : 0;
  const startsLater = !!form.startAt && new Date(form.startAt) > new Date();

  const stepContent: Record<StepId, ReactNode> = {
    agent: (
      <div className="stack">
        <Field label="Campaign name" error={errors.name}>
          <input
            className="input"
            value={form.name}
            placeholder="November EMI reminders"
            onChange={(e) => set({ name: e.target.value })}
            autoFocus
          />
        </Field>
        <div className="form-grid">
          <Field
            label="Agent"
            error={errors.agent_id}
            hint={agent ? `${agent.app_id} v${agent.app_version} · ${agent.variables.length} variables` : undefined}
          >
            <select className="select" value={form.agentId} onChange={(e) => set({ agentId: e.target.value })}>
              <option value="">Choose an agent…</option>
              {agents.data?.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Connection" error={errors.connection_id} hint={connection ? `ID ${connection.connection_id}` : undefined}>
            <select className="select" value={form.connectionId} onChange={(e) => set({ connectionId: e.target.value })}>
              <option value="">Choose a connection…</option>
              {connections.data?.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name} ({c.caller_numbers.length} numbers)
                </option>
              ))}
            </select>
          </Field>
        </div>
        {connection && <CallerNumbersField form={form} set={set} errors={errors} available={connection.caller_numbers} />}
        <OverridesFields form={form} set={set} errors={errors} />
      </div>
    ),
    recipients: agent ? (
      <CohortUploader
        value={cohort}
        onChange={setCohort}
        agent={agent}
        runDryRun={(file) => agentApi.validateCohort(agent.id, file)}
        note="Checked against the agent's variables and your Do Not Disturb list."
      />
    ) : (
      <Banner tone="info" title="Choose an agent first">
        The CSV columns come from the agent's variables.
      </Banner>
    ),
    schedule: (
      <div className="stack" style={{ gap: 20 }}>
        <ScheduleFields form={form} set={set} errors={errors} />
        <div className="fieldset">
          <div className="fieldset__title">Pacing & retries</div>
          <p className="fieldset__desc">How fast new calls start, and what happens when a call doesn't connect properly.</p>
          <div className="stack">
            <PacingFields form={form} set={set} errors={errors} orgCps={org.data?.max_calls_per_second} />
            <RetryFields form={form} set={set} errors={errors} />
          </div>
        </div>
      </div>
    ),
    review: (
      <div className="stack">
        <CampaignSummary settings={toSettings(form)} agent={agent} connection={connection} onEdit={(id) => goTo(id)} />
        <div className="summary">
          <div className="summary__head">
            <h3>Recipients</h3>
            <button type="button" className="link-btn" onClick={() => goTo("recipients")}>
              Edit
            </button>
          </div>
          {importCount > 0 && cohort.file && cohort.check ? (
            <p>
              <strong>{formatNumber(importCount)}</strong> contacts from <span className="mono">{cohort.file.name}</span>
              {cohort.skipInvalid && cohort.check.rows_rejected > 0 && (
                <span className="muted"> ({formatNumber(cohort.check.rows_rejected)} invalid rows skipped)</span>
              )}
              {cohort.check.dnd_skipped > 0 && (
                <span className="muted"> ({formatNumber(cohort.check.dnd_skipped)} on Do Not Disturb)</span>
              )}
            </p>
          ) : (
            <p className="muted">No recipients yet. Save as a draft and upload a CSV from the campaign page.</p>
          )}
        </div>
        {startsLater && importCount > 0 && (
          <Banner tone="info" title="Launching schedules this campaign">
            It starts calling at {formatDateTime(toSettings(form).start_at)}, inside its calling window.
          </Banner>
        )}
      </div>
    ),
  };

  const recipientsBlocked = step === "recipients" && !!cohort.file && !cohortReady(cohort);

  return (
    <>
      {header}
      <ol className="stepper" aria-label="Steps">
        {STEPS.map((s, i) => (
          <li key={s.id} className={`stepper__item ${i < stepIndex ? "is-done" : ""} ${i === stepIndex ? "is-current" : ""}`}>
            <button type="button" onClick={() => goTo(s.id)} aria-current={i === stepIndex ? "step" : undefined}>
              <span className="stepper__dot">{i < stepIndex ? <Check size={13} strokeWidth={3} /> : i + 1}</span>
              <span className="stepper__label">{s.label}</span>
            </button>
          </li>
        ))}
      </ol>

      <div className="card wizard">
        <div className="card__body">
          {serverError != null && (
            <div style={{ marginBottom: 16 }}>
              <ErrorBanner error={serverError} shownFields={SETTINGS_FIELDS} />
            </div>
          )}
          {stepContent[step]}
        </div>
        <div className="card__footer">
          {stepIndex > 0 && <Button onClick={() => setStep(STEPS[stepIndex - 1].id)}>Back</Button>}
          <div className="spacer" />
          {step === "recipients" && !cohort.file && (
            <span className="muted small">You can also add recipients later.</span>
          )}
          {step === "review" ? (
            <>
              <Button loading={submitting === "draft"} disabled={!!submitting} onClick={() => finish(false)}>
                Save as draft
              </Button>
              <Button
                variant="primary"
                icon={<Rocket size={15} />}
                loading={submitting === "launch"}
                disabled={!!submitting || importCount === 0}
                title={importCount === 0 ? "Add recipients before launching" : undefined}
                onClick={() => finish(true)}
              >
                {startsLater ? "Schedule launch" : "Launch now"}
              </Button>
            </>
          ) : (
            <Button
              variant="primary"
              onClick={() => goTo(STEPS[stepIndex + 1].id)}
              disabled={recipientsBlocked}
              title={recipientsBlocked ? "Check the file and fix or skip invalid rows first" : undefined}
            >
              Next
            </Button>
          )}
        </div>
      </div>
    </>
  );
}
