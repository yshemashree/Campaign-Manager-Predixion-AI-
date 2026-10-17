// Form state for campaign settings, shared by the "new campaign" wizard and the edit dialog.
// Inputs hold strings; conversion to the API shape happens in one place (toSettings).

import {
  RETRY_OUTCOMES,
  type Campaign,
  type CampaignSettings,
  type Connection,
  type RetryOutcome,
} from "../../api/types";
import { isoToLocalInput, localInputToIso } from "../../lib/format";

export interface RuleForm {
  enabled: boolean;
  delayMin: string;
}

export interface CampaignForm {
  name: string;
  agentId: string;
  connectionId: string;
  allNumbers: boolean;
  callerNumbers: string[];
  attemptsPerSecond: string;
  maxAttempts: string;
  backoff: string;
  shortCallThreshold: string;
  rules: Record<RetryOutcome, RuleForm>;
  startAt: string;
  endAt: string;
  timezone: string;
  days: number[];
  windowStart: string;
  windowEnd: string;
  greeting: string;
  stateName: string;
}

export type FormErrors = Record<string, string>;

// Mirrors the backend's DEFAULT_RETRY_POLICY and CallingWindowIn defaults.
export function defaultForm(): CampaignForm {
  return {
    name: "",
    agentId: "",
    connectionId: "",
    allNumbers: true,
    callerNumbers: [],
    attemptsPerSecond: "1",
    maxAttempts: "3",
    backoff: "1",
    shortCallThreshold: "10",
    rules: {
      busy: { enabled: true, delayMin: "10" },
      no_answer: { enabled: true, delayMin: "30" },
      short_call: { enabled: true, delayMin: "60" },
      failed: { enabled: false, delayMin: "15" },
    },
    startAt: "",
    endAt: "",
    timezone: "Asia/Kolkata",
    days: [1, 2, 3, 4, 5, 6],
    windowStart: "09:00",
    windowEnd: "21:00",
    greeting: "",
    stateName: "",
  };
}

const minutes = (seconds: number) => String(Math.round((seconds / 60) * 100) / 100);

export function campaignToForm(c: Campaign, connection?: Connection): CampaignForm {
  const rp = c.retry_policy;
  const sameAsConnection =
    !!connection &&
    connection.caller_numbers.length === c.caller_numbers.length &&
    connection.caller_numbers.every((n) => c.caller_numbers.includes(n));
  return {
    name: c.name,
    agentId: c.agent_id,
    connectionId: c.connection_id,
    allNumbers: sameAsConnection,
    callerNumbers: c.caller_numbers,
    attemptsPerSecond: String(c.attempts_per_second),
    maxAttempts: String(rp.max_attempts),
    backoff: String(rp.backoff),
    shortCallThreshold: String(rp.short_call_threshold_s),
    rules: Object.fromEntries(
      RETRY_OUTCOMES.map((o) => [o, { enabled: rp.rules[o]?.enabled ?? false, delayMin: minutes(rp.rules[o]?.delay_s ?? 0) }]),
    ) as Record<RetryOutcome, RuleForm>,
    startAt: isoToLocalInput(c.start_at),
    endAt: isoToLocalInput(c.end_at),
    timezone: c.calling_window.timezone,
    days: c.calling_window.days,
    windowStart: c.calling_window.start,
    windowEnd: c.calling_window.end,
    greeting: c.app_overrides.initial_bot_message ?? "",
    stateName: c.app_overrides.initial_state_name ?? "",
  };
}

export function toSettings(f: CampaignForm): CampaignSettings {
  return {
    name: f.name.trim(),
    caller_numbers: f.allNumbers ? null : f.callerNumbers,
    attempts_per_second: Number(f.attemptsPerSecond),
    retry_policy: {
      max_attempts: Number(f.maxAttempts),
      backoff: Number(f.backoff),
      short_call_threshold_s: Number(f.shortCallThreshold),
      rules: Object.fromEntries(
        RETRY_OUTCOMES.map((o) => [
          o,
          { enabled: f.rules[o].enabled, delay_s: Math.round(Number(f.rules[o].delayMin) * 60) },
        ]),
      ) as CampaignSettings["retry_policy"]["rules"],
    },
    calling_window: {
      timezone: f.timezone,
      days: [...f.days].sort(),
      start: f.windowStart,
      end: f.windowEnd,
    },
    start_at: localInputToIso(f.startAt),
    end_at: localInputToIso(f.endAt),
    app_overrides: {
      initial_bot_message: f.greeting.trim() || null,
      initial_state_name: f.stateName.trim() || null,
    },
  };
}

function inRange(value: string, min: number, max: number): boolean {
  const n = Number(value);
  return value.trim() !== "" && Number.isFinite(n) && n >= min && n <= max;
}

// Client-side checks keyed by the same field paths the API uses, so both kinds of error
// land under the same inputs.
export function validateBasics(f: CampaignForm): FormErrors {
  const e: FormErrors = {};
  if (f.name.trim().length < 2) e.name = "Give the campaign a name (at least 2 characters)";
  if (!f.agentId) e.agent_id = "Pick an agent";
  if (!f.connectionId) e.connection_id = "Pick a connection";
  if (!f.allNumbers && f.callerNumbers.length === 0) e.caller_numbers = "Pick at least one caller number";
  return e;
}

export function validatePacing(f: CampaignForm): FormErrors {
  const e: FormErrors = {};
  if (!inRange(f.attemptsPerSecond, 0.1, 500)) e.attempts_per_second = "Between 0.1 and 500";
  if (!inRange(f.maxAttempts, 1, 10) || !Number.isInteger(Number(f.maxAttempts)))
    e["retry_policy.max_attempts"] = "A whole number from 1 to 10";
  if (!inRange(f.backoff, 1, 5)) e["retry_policy.backoff"] = "Between 1 and 5";
  if (!inRange(f.shortCallThreshold, 0, 600)) e["retry_policy.short_call_threshold_s"] = "Between 0 and 600 seconds";
  for (const o of RETRY_OUTCOMES) {
    if (f.rules[o].enabled && !inRange(f.rules[o].delayMin, 0, 7 * 24 * 60))
      e[`retry_policy.rules.${o}.delay_s`] = "Between 0 and 10080 minutes (7 days)";
  }
  return e;
}

export function validateSchedule(f: CampaignForm): FormErrors {
  const e: FormErrors = {};
  if (f.days.length === 0) e["calling_window.days"] = "Pick at least one day";
  if (!f.windowStart) e["calling_window.start"] = "Required";
  if (!f.windowEnd) e["calling_window.end"] = "Required";
  if (f.windowStart && f.windowEnd && f.windowStart >= f.windowEnd)
    e["calling_window.end"] = "Must be after the start time (overnight windows aren't supported)";
  if (f.startAt && f.endAt && new Date(f.endAt) <= new Date(f.startAt)) e.end_at = "Must be after the start";
  return e;
}

/** Which wizard step an API error field belongs to. */
export function stepForField(field: string): "agent" | "schedule" {
  const scheduleFields = ["attempts_per_second", "start_at", "end_at", ""];
  if (scheduleFields.includes(field) || field.startsWith("retry_policy") || field.startsWith("calling_window"))
    return "schedule";
  return "agent";
}
