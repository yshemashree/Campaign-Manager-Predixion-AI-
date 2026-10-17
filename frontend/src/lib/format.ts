// Display helpers for dates, numbers and status words.

const dateTime = new Intl.DateTimeFormat(undefined, {
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

const shortDateTime = new Intl.DateTimeFormat(undefined, {
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
});

const timeOnly = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return dateTime.format(new Date(iso));
}

/** Time only for today, otherwise date and time. Good for busy tables. */
export function formatCompact(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  const now = new Date();
  return d.toDateString() === now.toDateString() ? timeOnly.format(d) : shortDateTime.format(d);
}

const relative = new Intl.RelativeTimeFormat(undefined, { numeric: "auto", style: "short" });

export function formatRelative(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "—";
  const diffS = Math.round((new Date(iso).getTime() - now) / 1000);
  const abs = Math.abs(diffS);
  // A few seconds of clock difference between server and browser shouldn't read as the future.
  if (abs < 45) return diffS > 5 ? "in a few seconds" : "just now";
  if (abs < 45 * 60) return relative.format(Math.round(diffS / 60), "minute");
  if (abs < 22 * 3600) return relative.format(Math.round(diffS / 3600), "hour");
  return relative.format(Math.round(diffS / 86400), "day");
}

export function formatNumber(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString();
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return s ? `${m}m ${s}s` : `${m}m`;
}

export function percent(part: number, total: number): number {
  return total > 0 ? Math.round((part / total) * 1000) / 10 : 0;
}

/** "no_answer" -> "No answer" */
export function humanize(value: string | null | undefined): string {
  if (!value) return "—";
  const text = value.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

// ---------- time zones ----------

/** Short zone name like "IST" or "EDT"; falls back to "GMT+5:30" style when there is none. */
export function zoneAbbreviation(timeZone: string, at: Date = new Date()): string {
  const pick = (locale: string) =>
    new Intl.DateTimeFormat(locale, { timeZone, timeZoneName: "short" })
      .formatToParts(at)
      .find((p) => p.type === "timeZoneName")?.value ?? "";
  try {
    const us = pick("en-US");
    if (!us.startsWith("GMT") && !us.startsWith("UTC")) return us;
    const india = pick("en-IN");
    return india && !india.startsWith("GMT") ? india : us;
  } catch {
    return timeZone;
  }
}

/** Wall-clock time in a zone, e.g. "18:00 IST". */
export function formatZoneTime(iso: string, timeZone: string): string {
  const d = new Date(iso);
  const hm = new Intl.DateTimeFormat("en-GB", { timeZone, hour: "2-digit", minute: "2-digit" }).format(d);
  return `${hm} ${zoneAbbreviation(timeZone, d)}`;
}

/** "Mon 09:00 IST" within a week, otherwise "12 Nov 09:00 IST". */
export function formatZoneDayTime(iso: string, timeZone: string): string {
  const d = new Date(iso);
  const withinWeek = d.getTime() - Date.now() < 6 * 86400 * 1000;
  const day = new Intl.DateTimeFormat("en-GB", {
    timeZone,
    ...(withinWeek ? { weekday: "short" } : { day: "numeric", month: "short" }),
  }).format(d);
  return `${day} ${formatZoneTime(iso, timeZone)}`;
}

export function browserTimeZone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone;
}

/** Offset of the browser's zone at a given moment, e.g. "+05:30". */
function offsetString(d: Date): string {
  const minutes = -d.getTimezoneOffset();
  const sign = minutes >= 0 ? "+" : "-";
  const abs = Math.abs(minutes);
  const hh = String(Math.floor(abs / 60)).padStart(2, "0");
  const mm = String(abs % 60).padStart(2, "0");
  return `${sign}${hh}:${mm}`;
}

/** datetime-local value ("2026-11-01T09:00") -> ISO with the browser's offset. */
export function localInputToIso(value: string): string | null {
  if (!value) return null;
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return null;
  const seconds = value.length === 16 ? `${value}:00` : value;
  return `${seconds}${offsetString(d)}`;
}

/** ISO instant -> datetime-local value in the browser's zone. */
export function isoToLocalInput(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export const WEEKDAYS = [
  { value: 1, short: "Mon" },
  { value: 2, short: "Tue" },
  { value: 3, short: "Wed" },
  { value: 4, short: "Thu" },
  { value: 5, short: "Fri" },
  { value: 6, short: "Sat" },
  { value: 7, short: "Sun" },
];

export function describeDays(days: number[]): string {
  const sorted = [...days].sort();
  if (sorted.length === 7) return "Every day";
  if (sorted.join() === "1,2,3,4,5") return "Mon to Fri";
  if (sorted.join() === "1,2,3,4,5,6") return "Mon to Sat";
  return sorted.map((d) => WEEKDAYS[d - 1]?.short).join(", ");
}

const FALLBACK_ZONES = [
  "Asia/Kolkata",
  "Asia/Dubai",
  "Asia/Singapore",
  "Asia/Tokyo",
  "Europe/London",
  "Europe/Berlin",
  "America/New_York",
  "America/Chicago",
  "America/Los_Angeles",
  "Australia/Sydney",
  "UTC",
];

export function timeZones(): string[] {
  const intl = Intl as unknown as { supportedValuesOf?: (key: string) => string[] };
  const zones = new Set(intl.supportedValuesOf?.("timeZone") ?? FALLBACK_ZONES);
  // Some browsers still list the old alias; the backend default is the current name.
  zones.delete("Asia/Calcutta");
  zones.add("Asia/Kolkata");
  zones.add("UTC");
  return [...zones].sort();
}
