import { humanize } from "../lib/format";

type Colour = "grey" | "blue" | "indigo" | "green" | "amber" | "red" | "teal";

const COLOURS: Record<string, Colour> = {
  // campaigns
  draft: "grey",
  scheduled: "indigo",
  running: "green",
  paused: "amber",
  stopped: "red",
  // contacts
  pending: "grey",
  dialing: "blue",
  in_progress: "indigo",
  retry_scheduled: "amber",
  completed: "green",
  failed: "red",
  cancelled: "grey",
  // call attempts
  reserved: "grey",
  dispatched: "blue",
  unknown: "amber",
  busy: "amber",
  no_answer: "amber",
  short_call: "amber",
  rejected: "red",
  lost: "red",
};

const LABELS: Record<string, string> = {
  in_progress: "In progress",
  retry_scheduled: "Retry scheduled",
  no_answer: "No answer",
  short_call: "Short call",
};

export function StatusPill({ status, kind }: { status: string; kind?: "campaign" | "contact" | "attempt" }) {
  // A finished campaign is shown in blue so it doesn't look like a running one at a glance.
  const colour = kind === "campaign" && status === "completed" ? "blue" : (COLOURS[status] ?? "grey");
  const live = status === "running" || status === "dialing" || status === "in_progress";
  return (
    <span className={`pill pill--${colour} ${live ? "pill--pulse" : ""}`}>{LABELS[status] ?? humanize(status)}</span>
  );
}

const ROLE_LABELS: Record<string, string> = {
  superadmin: "Superadmin",
  org_admin: "Org admin",
  member: "Member",
};

export function roleLabel(role: string): string {
  return ROLE_LABELS[role] ?? humanize(role);
}
