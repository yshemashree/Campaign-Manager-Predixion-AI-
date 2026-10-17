import { useMemo } from "react";
import { RETRY_OUTCOMES, type RetryOutcome } from "../../api/types";
import { Field, Switch } from "../../components/Field";
import { browserTimeZone, timeZones, WEEKDAYS, zoneAbbreviation } from "../../lib/format";
import type { CampaignForm, FormErrors } from "./settingsForm";

interface SectionProps {
  form: CampaignForm;
  set: (patch: Partial<CampaignForm>) => void;
  errors: FormErrors;
  disabled?: boolean;
}

export function CallerNumbersField({ form, set, errors, available, disabled }: SectionProps & { available: string[] }) {
  const toggle = (n: string) =>
    set({
      callerNumbers: form.callerNumbers.includes(n)
        ? form.callerNumbers.filter((x) => x !== n)
        : [...form.callerNumbers, n],
    });
  return (
    <div className="field">
      <span className="field__label">Caller numbers</span>
      <div className="stack-sm">
        <label className="check">
          <input
            type="radio"
            name="caller-numbers"
            checked={form.allNumbers}
            disabled={disabled}
            onChange={() => set({ allNumbers: true })}
          />
          All numbers on the connection{available.length ? ` (${available.length})` : ""}
        </label>
        <label className="check">
          <input
            type="radio"
            name="caller-numbers"
            checked={!form.allNumbers}
            disabled={disabled || available.length === 0}
            onChange={() => set({ allNumbers: false, callerNumbers: form.callerNumbers.length ? form.callerNumbers : [] })}
          />
          Only some of them
        </label>
        {!form.allNumbers && (
          <div className="chip-list" style={{ paddingLeft: 24 }}>
            {available.map((n) => (
              <label key={n} className="chip mono" style={{ cursor: "pointer", height: 28 }}>
                <input
                  type="checkbox"
                  className="check-input"
                  checked={form.callerNumbers.includes(n)}
                  disabled={disabled}
                  onChange={() => toggle(n)}
                />
                {n}
              </label>
            ))}
          </div>
        )}
      </div>
      {errors.caller_numbers ? (
        <span className="field__error">{errors.caller_numbers}</span>
      ) : (
        <span className="field__hint">Calls rotate across the chosen numbers.</span>
      )}
    </div>
  );
}

export function OverridesFields({ form, set, errors, disabled }: SectionProps) {
  const open = !!(form.greeting || form.stateName);
  return (
    <details className="disclosure" open={open}>
      <summary>Override the agent's opening for this campaign</summary>
      <div className="stack" style={{ marginTop: 12 }}>
        <Field
          label="Initial bot message"
          optional
          hint="Leave blank to use the agent's own message."
          error={errors["app_overrides.initial_bot_message"]}
        >
          <textarea
            className="textarea"
            rows={2}
            style={{ minHeight: 60 }}
            value={form.greeting}
            disabled={disabled}
            onChange={(e) => set({ greeting: e.target.value })}
          />
        </Field>
        <Field label="Initial state name" optional error={errors["app_overrides.initial_state_name"]}>
          <input
            className="input mono"
            value={form.stateName}
            disabled={disabled}
            onChange={(e) => set({ stateName: e.target.value })}
          />
        </Field>
      </div>
    </details>
  );
}

export function PacingFields({ form, set, errors, disabled, orgCps }: SectionProps & { orgCps?: number }) {
  return (
    <Field
      label="Attempts per second"
      error={errors.attempts_per_second}
      hint={
        orgCps !== undefined
          ? `How fast this campaign starts new calls. Your organisation allows ${orgCps} calls per second across all campaigns.`
          : "How fast this campaign starts new calls."
      }
    >
      <input
        className="input"
        type="number"
        min={0.1}
        max={500}
        step={0.1}
        style={{ maxWidth: 200 }}
        value={form.attemptsPerSecond}
        disabled={disabled}
        onChange={(e) => set({ attemptsPerSecond: e.target.value })}
      />
    </Field>
  );
}

const OUTCOME_COPY: Record<RetryOutcome, { label: string; hint: string }> = {
  busy: { label: "Busy", hint: "The line was engaged" },
  no_answer: { label: "No answer", hint: "Rang out without being picked up" },
  short_call: { label: "Short call", hint: "Answered, but ended under the threshold" },
  failed: { label: "Failed", hint: "Network or provider failure, or no result received" },
};

export function RetryFields({ form, set, errors, disabled }: SectionProps) {
  const setRule = (o: RetryOutcome, patch: Partial<CampaignForm["rules"][RetryOutcome]>) =>
    set({ rules: { ...form.rules, [o]: { ...form.rules[o], ...patch } } });

  return (
    <div className="stack">
      <div className="grid-3">
        <Field
          label="Max attempts"
          hint="Per contact, including the first call"
          error={errors["retry_policy.max_attempts"]}
        >
          <input
            className="input"
            type="number"
            min={1}
            max={10}
            step={1}
            value={form.maxAttempts}
            disabled={disabled}
            onChange={(e) => set({ maxAttempts: e.target.value })}
          />
        </Field>
        <Field
          label="Backoff"
          hint="Each later retry waits this many times longer"
          error={errors["retry_policy.backoff"]}
          controlId="retry-backoff"
        >
          <div className="input-group">
            <input
              id="retry-backoff"
              className="input"
              type="number"
              min={1}
              max={5}
              step={0.1}
              value={form.backoff}
              disabled={disabled}
              onChange={(e) => set({ backoff: e.target.value })}
            />
            <span className="input-group__addon">×</span>
          </div>
        </Field>
        <Field
          label="Short call threshold"
          hint="Answered calls shorter than this count as short"
          error={errors["retry_policy.short_call_threshold_s"]}
          controlId="retry-short-call"
        >
          <div className="input-group">
            <input
              id="retry-short-call"
              className="input"
              type="number"
              min={0}
              max={600}
              step={1}
              value={form.shortCallThreshold}
              disabled={disabled}
              onChange={(e) => set({ shortCallThreshold: e.target.value })}
            />
            <span className="input-group__addon">seconds</span>
          </div>
        </Field>
      </div>

      <div className="fieldset" style={{ padding: 0, overflow: "hidden" }}>
        <table className="table table--compact">
          <thead>
            <tr>
              <th>Outcome</th>
              <th style={{ width: 90 }}>Retry</th>
              <th style={{ width: 220 }}>Retry after</th>
            </tr>
          </thead>
          <tbody>
            {RETRY_OUTCOMES.map((o) => {
              const rule = form.rules[o];
              const error = errors[`retry_policy.rules.${o}.delay_s`] ?? errors[`retry_policy.rules.${o}`];
              return (
                <tr key={o}>
                  <td>
                    <div className="cell-title">{OUTCOME_COPY[o].label}</div>
                    <div className="cell-sub">{OUTCOME_COPY[o].hint}</div>
                  </td>
                  <td>
                    <Switch
                      checked={rule.enabled}
                      disabled={disabled}
                      label={`Retry when ${OUTCOME_COPY[o].label.toLowerCase()}`}
                      onChange={(enabled) => setRule(o, { enabled })}
                    />
                  </td>
                  <td>
                    <div className="input-group">
                      <input
                        className="input input--sm"
                        type="number"
                        min={0}
                        step={1}
                        aria-label={`${OUTCOME_COPY[o].label} retry delay in minutes`}
                        aria-invalid={error ? true : undefined}
                        value={rule.delayMin}
                        disabled={disabled || !rule.enabled}
                        onChange={(e) => setRule(o, { delayMin: e.target.value })}
                      />
                      <span className="input-group__addon" style={{ height: 30 }}>
                        minutes
                      </span>
                    </div>
                    {error && <div className="field__error">{error}</div>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="muted small">
        Retries always land inside the calling window. Completed calls and rejected numbers are never retried.
      </p>
    </div>
  );
}

export function ScheduleFields({ form, set, errors, disabled }: SectionProps) {
  const zones = useMemo(() => {
    const all = timeZones();
    return all.includes(form.timezone) ? all : [form.timezone, ...all];
  }, [form.timezone]);
  const browserZone = browserTimeZone();
  const localLabel = `your time, ${zoneAbbreviation(browserZone)}`;
  const toggleDay = (d: number) =>
    set({ days: form.days.includes(d) ? form.days.filter((x) => x !== d) : [...form.days, d].sort() });

  return (
    <div className="stack">
      <div className="fieldset">
        <div className="fieldset__title">Campaign dates</div>
        <p className="fieldset__desc">
          Optional. Without a start the campaign begins as soon as you start it; without an end it runs until every
          contact is done.
        </p>
        <div className="form-grid">
          <Field label={`Start at (${localLabel})`} optional error={errors.start_at}>
            <input
              className="input"
              type="datetime-local"
              value={form.startAt}
              disabled={disabled}
              onChange={(e) => set({ startAt: e.target.value })}
            />
          </Field>
          <Field label={`End at (${localLabel})`} optional error={errors.end_at ?? errors[""]}>
            <input
              className="input"
              type="datetime-local"
              value={form.endAt}
              disabled={disabled}
              onChange={(e) => set({ endAt: e.target.value })}
            />
          </Field>
        </div>
      </div>

      <div className="fieldset">
        <div className="fieldset__title">Calling window</div>
        <p className="fieldset__desc">Calls are only placed on these days, between these times, in the chosen time zone.</p>
        <div className="stack">
          <Field label="Time zone" error={errors["calling_window.timezone"]}>
            <select
              className="select"
              style={{ maxWidth: 320 }}
              value={form.timezone}
              disabled={disabled}
              onChange={(e) => set({ timezone: e.target.value })}
            >
              {zones.map((z) => (
                <option key={z} value={z}>
                  {z.replace(/_/g, " ")}
                </option>
              ))}
            </select>
          </Field>
          <div className="field">
            <span className="field__label">Days</span>
            <div className="day-picker" role="group" aria-label="Calling days">
              {WEEKDAYS.map((d) => (
                <label key={d.value}>
                  <input
                    type="checkbox"
                    checked={form.days.includes(d.value)}
                    disabled={disabled}
                    onChange={() => toggleDay(d.value)}
                  />
                  <span>{d.short}</span>
                </label>
              ))}
            </div>
            {errors["calling_window.days"] && <span className="field__error">{errors["calling_window.days"]}</span>}
          </div>
          <div className="grid-2" style={{ maxWidth: 420 }}>
            <Field label="From" error={errors["calling_window.start"]}>
              <input
                className="input"
                type="time"
                value={form.windowStart}
                disabled={disabled}
                onChange={(e) => set({ windowStart: e.target.value })}
              />
            </Field>
            <Field label="Until" error={errors["calling_window.end"] ?? errors.calling_window}>
              <input
                className="input"
                type="time"
                value={form.windowEnd}
                disabled={disabled}
                onChange={(e) => set({ windowEnd: e.target.value })}
              />
            </Field>
          </div>
        </div>
      </div>
    </div>
  );
}

/** Field paths rendered by the sections above (for ErrorBanner's de-duplication). */
export const SETTINGS_FIELDS = [
  "name",
  "agent_id",
  "connection_id",
  "caller_numbers",
  "attempts_per_second",
  "retry_policy.max_attempts",
  "retry_policy.backoff",
  "retry_policy.short_call_threshold_s",
  ...RETRY_OUTCOMES.flatMap((o) => [`retry_policy.rules.${o}.delay_s`, `retry_policy.rules.${o}`]),
  "start_at",
  "end_at",
  "",
  "calling_window",
  "calling_window.timezone",
  "calling_window.days",
  "calling_window.start",
  "calling_window.end",
  "app_overrides.initial_bot_message",
  "app_overrides.initial_state_name",
];
