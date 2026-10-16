import type { ContactStatus } from "../api/types";

export type Counts = Partial<Record<ContactStatus, number>> | undefined;

// Colours for contact states in bars and swatches. Pending recedes; done states are strong.
export const STATUS_COLOURS: Record<string, string> = {
  pending: "#c9ced8",
  in_flight: "#2a78d6",
  retry_scheduled: "#eda100",
  completed: "#16a34a",
  failed: "#d03b3b",
  cancelled: "#7c8698",
};

export interface Segment {
  key: string;
  label: string;
  value: number;
  colour: string;
}

export function count(counts: Counts, status: ContactStatus): number {
  return counts?.[status] ?? 0;
}

/** Contact counts grouped the way the UI shows them: dialing and in progress together. */
export function segments(stats: Counts): Segment[] {
  return [
    { key: "completed", label: "Completed", value: count(stats, "completed"), colour: STATUS_COLOURS.completed },
    { key: "failed", label: "Failed", value: count(stats, "failed"), colour: STATUS_COLOURS.failed },
    { key: "cancelled", label: "Cancelled", value: count(stats, "cancelled"), colour: STATUS_COLOURS.cancelled },
    {
      key: "in_flight",
      label: "Dialing / in progress",
      value: count(stats, "dialing") + count(stats, "in_progress"),
      colour: STATUS_COLOURS.in_flight,
    },
    {
      key: "retry_scheduled",
      label: "Retry scheduled",
      value: count(stats, "retry_scheduled"),
      colour: STATUS_COLOURS.retry_scheduled,
    },
    { key: "pending", label: "Pending", value: count(stats, "pending"), colour: STATUS_COLOURS.pending },
  ];
}

export function finishedCount(stats: Counts): number {
  return count(stats, "completed") + count(stats, "failed") + count(stats, "cancelled");
}

export function totalCount(counts: Counts): number {
  return Object.values(counts ?? {}).reduce((sum, n) => sum + (n ?? 0), 0);
}
