import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Pause } from "lucide-react";
import { ApiError } from "../../../api/client";
import { campaignApi } from "../../../api/endpoints";
import { keys, useAgents, useConnections } from "../../../api/queries";
import type { Campaign, Connection } from "../../../api/types";
import { Button } from "../../../components/Button";
import { Banner, ErrorBanner } from "../../../components/Feedback";
import { Field } from "../../../components/Field";
import { Modal } from "../../../components/Overlay";
import { useToast } from "../../../components/Toast";
import {
  CallerNumbersField,
  OverridesFields,
  PacingFields,
  RetryFields,
  ScheduleFields,
  SETTINGS_FIELDS,
} from "../SettingsFields";
import {
  campaignToForm,
  toSettings,
  validateBasics,
  validatePacing,
  validateSchedule,
  type CampaignForm,
  type FormErrors,
} from "../settingsForm";

interface Props {
  campaign: Campaign;
  connection?: Connection;
  orgCps?: number;
  onPause: () => void;
  pausing: boolean;
  onClose: () => void;
}

export function EditSettingsModal({ campaign, connection, orgCps, onPause, pausing, onClose }: Props) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [form, setForm] = useState<CampaignForm>(() => campaignToForm(campaign, connection));
  const [errors, setErrors] = useState<FormErrors>({});
  const set = (patch: Partial<CampaignForm>) => setForm((f) => ({ ...f, ...patch }));
  const running = campaign.status === "running";
  const draft = campaign.status === "draft";
  const agents = useAgents(draft ? campaign.workspace_id : null);
  const connections = useConnections(campaign.workspace_id);
  const selectedConnection = connections.data?.find((c) => c.id === form.connectionId) ?? connection;

  const save = useMutation({
    // Agent, connection and caller numbers can only change while the campaign is a draft.
    mutationFn: () => {
      const { caller_numbers, ...settings } = toSettings(form);
      return campaignApi.update(
        campaign.id,
        draft ? { ...settings, caller_numbers, agent_id: form.agentId, connection_id: form.connectionId } : settings,
      );
    },
    onSuccess: (updated) => {
      queryClient.setQueryData(keys.campaign(campaign.id), updated);
      queryClient.invalidateQueries({ queryKey: keys.stats(campaign.id), exact: true });
      toast.success("Settings saved", updated.name);
      onClose();
    },
    onError: (err) => setErrors(err instanceof ApiError ? err.fieldErrors() : {}),
  });

  function submit() {
    const found = { ...validateBasics(form), ...validatePacing(form), ...validateSchedule(form) };
    setErrors(found);
    if (Object.keys(found).length === 0) save.mutate();
  }

  const conflict = save.error instanceof ApiError && save.error.status === 409;

  return (
    <Modal
      wide
      title="Campaign settings"
      description="Changes apply to calls placed from now on."
      onClose={onClose}
      onSubmit={submit}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="primary" loading={save.isPending} disabled={running}>
            Save settings
          </Button>
        </>
      }
    >
      <div className="stack" style={{ gap: 20 }}>
        {(running || conflict) && (
          <Banner tone="warning" title="This campaign is dialing">
            <p>Settings can only change while nothing is being dialed. Pause the campaign, edit, then resume it.</p>
            {running && (
              <div style={{ marginTop: 8 }}>
                <Button size="sm" icon={<Pause size={14} />} loading={pausing} onClick={onPause}>
                  Pause campaign
                </Button>
              </div>
            )}
          </Banner>
        )}
        {save.isError && !conflict && <ErrorBanner error={save.error} shownFields={SETTINGS_FIELDS} />}

        <section className="stack">
          <h3 className="section-title" style={{ margin: 0 }}>
            General
          </h3>
          <Field label="Name" error={errors.name}>
            <input className="input" value={form.name} disabled={running} onChange={(e) => set({ name: e.target.value })} />
          </Field>
          {draft && (
            <div className="form-grid">
              <Field label="Agent" error={errors.agent_id} hint="Changing the agent changes which CSV columns are expected.">
                <select className="select" value={form.agentId} onChange={(e) => set({ agentId: e.target.value })}>
                  {agents.data?.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Connection" error={errors.connection_id}>
                <select
                  className="select"
                  value={form.connectionId}
                  onChange={(e) => set({ connectionId: e.target.value, allNumbers: true, callerNumbers: [] })}
                >
                  {connections.data?.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
          )}
          <CallerNumbersField
            form={form}
            set={set}
            errors={errors}
            available={selectedConnection?.caller_numbers ?? campaign.caller_numbers}
            disabled={!draft}
          />
          <OverridesFields form={form} set={set} errors={errors} disabled={running} />
        </section>

        <hr className="divider" />
        <section className="stack">
          <h3 className="section-title" style={{ margin: 0 }}>
            Pacing and retries
          </h3>
          <PacingFields form={form} set={set} errors={errors} disabled={running} orgCps={orgCps} />
          <RetryFields form={form} set={set} errors={errors} disabled={running} />
        </section>

        <hr className="divider" />
        <section className="stack">
          <h3 className="section-title" style={{ margin: 0 }}>
            Schedule
          </h3>
          <ScheduleFields form={form} set={set} errors={errors} disabled={running} />
        </section>
      </div>
    </Modal>
  );
}
