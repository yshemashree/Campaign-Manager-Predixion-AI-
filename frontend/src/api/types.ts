// Shapes returned and accepted by the API (see backend/app/schemas).

export type Role = "superadmin" | "org_admin" | "member";

export interface User {
  id: string;
  email: string;
  full_name: string;
  role: Role;
  org_id: string | null;
  is_active: boolean;
  workspace_ids: string[];
}

export interface TokenResponse {
  access_token: string;
  token_type: "bearer";
  user: User;
}

export interface Organization {
  id: string;
  name: string;
  sarvam_org_id: string | null;
  max_concurrent_calls: number;
  max_calls_per_second: number;
  limit_version: number;
  is_active: boolean;
  created_at: string;
}

export interface OrganizationCreate {
  name: string;
  sarvam_org_id?: string | null;
  max_concurrent_calls: number;
  max_calls_per_second: number;
  admin_email?: string | null;
  admin_password?: string | null;
  admin_name?: string;
}

export type OrganizationUpdate = Partial<
  Pick<Organization, "name" | "sarvam_org_id" | "max_concurrent_calls" | "max_calls_per_second" | "is_active">
>;

export interface Workspace {
  id: string;
  org_id: string;
  name: string;
  sarvam_workspace_id: string | null;
  sarvam_api_key_last4: string | null;
  created_at: string;
}

export interface WorkspaceInput {
  name?: string;
  sarvam_workspace_id?: string | null;
  sarvam_api_key?: string;
}

export interface UserCreate {
  email: string;
  password: string;
  full_name: string;
  role: "org_admin" | "member";
  workspace_ids: string[];
  org_id?: string;
}

export interface UserUpdate {
  full_name?: string;
  role?: "org_admin" | "member";
  is_active?: boolean;
  password?: string;
  workspace_ids?: string[];
}

export const VARIABLE_TYPES = ["string", "number", "integer", "boolean", "date", "enum"] as const;
export type VariableType = (typeof VARIABLE_TYPES)[number];

export interface AgentVariable {
  name: string;
  type: VariableType;
  required: boolean;
  example: string;
  allowed: string[];
  max_length?: number;
}

export interface Agent {
  id: string;
  workspace_id: string;
  name: string;
  app_id: string;
  app_version: number;
  variables: AgentVariable[];
  initial_bot_message: string | null;
  initial_state_name: string | null;
  created_at: string;
}

export interface AgentInput {
  name: string;
  app_id: string;
  app_version: number;
  variables: AgentVariable[];
  initial_bot_message: string | null;
  initial_state_name: string | null;
}

export interface Connection {
  id: string;
  workspace_id: string;
  name: string;
  connection_id: string;
  caller_numbers: string[];
  created_at: string;
}

export interface ConnectionInput {
  name: string;
  connection_id: string;
  caller_numbers: string[];
}

export const CAMPAIGN_STATUSES = ["draft", "scheduled", "running", "paused", "stopped", "completed"] as const;
export type CampaignStatus = (typeof CAMPAIGN_STATUSES)[number];

export const CONTACT_STATUSES = [
  "pending",
  "dialing",
  "in_progress",
  "retry_scheduled",
  "completed",
  "failed",
  "cancelled",
] as const;
export type ContactStatus = (typeof CONTACT_STATUSES)[number];

export type LifecycleAction = "start" | "pause" | "resume" | "stop";

export const RETRY_OUTCOMES = ["busy", "no_answer", "short_call", "failed"] as const;
export type RetryOutcome = (typeof RETRY_OUTCOMES)[number];

export interface RetryRule {
  enabled: boolean;
  delay_s: number;
}

export interface RetryPolicy {
  max_attempts: number;
  short_call_threshold_s: number;
  backoff: number;
  rules: Record<RetryOutcome, RetryRule>;
}

export interface CallingWindow {
  timezone: string;
  days: number[];
  start: string;
  end: string;
}

export interface AppOverrides {
  initial_bot_message?: string | null;
  initial_state_name?: string | null;
}

export interface Campaign {
  id: string;
  org_id: string;
  workspace_id: string;
  agent_id: string;
  connection_id: string;
  name: string;
  status: CampaignStatus;
  state_version: number;
  pause_reason: string | null;
  attempts_per_second: number;
  caller_numbers: string[];
  retry_policy: RetryPolicy;
  calling_window: CallingWindow;
  start_at: string | null;
  end_at: string | null;
  app_overrides: AppOverrides;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  contact_counts: Partial<Record<ContactStatus, number>>;
}

export interface CampaignSettings {
  name: string;
  caller_numbers: string[] | null;
  attempts_per_second: number;
  retry_policy: RetryPolicy;
  calling_window: CallingWindow;
  start_at: string | null;
  end_at: string | null;
  app_overrides: AppOverrides;
}

export interface CampaignUpdate extends Partial<CampaignSettings> {
  // Only accepted while the campaign is a draft.
  agent_id?: string;
  connection_id?: string;
}

export interface CampaignCreate extends CampaignSettings {
  agent_id: string;
  connection_id: string;
}

export interface CampaignStats {
  campaign_id: string;
  status: CampaignStatus;
  total: number;
  by_status: Partial<Record<ContactStatus, number>>;
  attempts_total: number;
  in_window: boolean;
  window_closes_at: string | null;
  next_window_opens_at: string | null;
}

export interface Cohort {
  id: string;
  campaign_id: string;
  filename: string;
  rows_total: number;
  rows_accepted: number;
  rows_rejected: number;
  rows_duplicate: number;
  created_at: string;
}

export interface RowError {
  row: number;
  column: string;
  message: string;
}

export interface CohortUploadResult {
  dry_run: boolean;
  accepted: boolean;
  cohort: Cohort | null;
  rows_total: number;
  rows_valid: number;
  rows_rejected: number;
  duplicates_in_file: number;
  duplicates_existing: number;
  dnd_skipped: number;
  header_errors: string[];
  errors: RowError[];
  error_report_csv: string | null;
}

export interface Contact {
  id: string;
  campaign_id: string;
  phone_e164: string;
  lead_id: string;
  variables: Record<string, unknown>;
  status: ContactStatus;
  attempts_made: number;
  next_attempt_at: string | null;
  last_outcome: string | null;
  final_reason: string | null;
  updated_at: string;
}

export interface Attempt {
  id: string;
  attempt_no: number;
  status: string;
  from_number: string | null;
  provider_attempt_id: string | null;
  http_status: number | null;
  created_at: string;
  dispatched_at: string | null;
  ended_at: string | null;
  duration_s: number | null;
  failure_reason: string | null;
}

export interface ContactDetail extends Contact {
  attempts: Attempt[];
}

export interface ContactPage {
  items: Contact[];
  next_cursor: string | null;
  total: number;
}

export interface OrgRate {
  org_id: string;
  max_calls_per_second: number;
  max_concurrent_calls: number;
  live_calls: number;
  per_second: { t: number; calls: number }[];
  live_per_second: { t: number; calls: number }[];
  max_in_any_rolling_second: number;
}

// Messages pushed over the campaign event stream ("updates" event).
export type LiveEvent =
  | {
      type: "contact.updated";
      at: string;
      contact_id: string;
      status: ContactStatus;
      attempts_made: number;
      attempt_status?: string;
      next_attempt_at?: string | null;
      last_outcome?: string | null;
      updated_at?: string;
    }
  | { type: "campaign.updated"; at: string; status?: CampaignStatus; pause_reason?: string };

export interface DndEntry {
  id: string;
  phone_e164: string;
  reason: string | null;
  created_at: string;
}

export interface DndPage {
  items: DndEntry[];
  next_cursor: string | null;
  total: number;
}

export interface DndAddResult {
  added: number;
  already_listed: number;
  invalid: string[];
}
