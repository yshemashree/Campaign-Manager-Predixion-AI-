import { useEffect, useState } from "react";
import { ChevronLeft, ChevronRight, Search, Users } from "lucide-react";
import { useContactPage } from "../../../api/queries";
import { CONTACT_STATUSES, type CampaignStats, type Contact, type ContactStatus } from "../../../api/types";
import { Button } from "../../../components/Button";
import { EmptyState, QueryError, SkeletonRows } from "../../../components/Feedback";
import { StatusPill } from "../../../components/StatusPill";
import { RelativeTime } from "../../../components/RelativeTime";
import { formatNumber, humanize } from "../../../lib/format";

const PAGE_SIZE = 50;

const STATUS_LABEL: Record<ContactStatus, string> = {
  pending: "Pending",
  dialing: "Dialing",
  in_progress: "In progress",
  retry_scheduled: "Retry scheduled",
  completed: "Completed",
  failed: "Failed",
  cancelled: "Cancelled",
};

function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return debounced;
}

interface Props {
  campaignId: string;
  stats?: CampaignStats;
  flash: ReadonlyMap<string, number>;
  selectedId: string | null;
  onSelect: (contact: Contact) => void;
  /** Refetch interval when live updates aren't flowing. */
  pollMs: number | false;
}

export function ContactsTable({ campaignId, stats, flash, selectedId, onSelect, pollMs }: Props) {
  const [status, setStatus] = useState<ContactStatus | "">("");
  const [search, setSearch] = useState("");
  const q = useDebounced(search.trim(), 300);
  // Keyset pagination: remember the cursor that opened each page so "Previous" works.
  const [cursors, setCursors] = useState<(string | undefined)[]>([undefined]);
  const page = cursors.length - 1;

  useEffect(() => setCursors([undefined]), [status, q]);

  const query = { status: status || undefined, q: q || undefined, cursor: cursors[page], limit: PAGE_SIZE };
  const contacts = useContactPage(campaignId, query, pollMs);

  const items = contacts.data?.items ?? [];
  const nextCursor = contacts.data?.next_cursor ?? null;
  const total = contacts.data?.total ?? 0;
  const firstRow = page * PAGE_SIZE + 1;

  return (
    <div>
      <div className="toolbar">
        <select
          className="select select--sm"
          style={{ width: 220 }}
          aria-label="Filter by status"
          value={status}
          onChange={(e) => setStatus(e.target.value as ContactStatus | "")}
        >
          <option value="">All statuses{stats ? ` (${formatNumber(stats.total)})` : ""}</option>
          {CONTACT_STATUSES.map((s) => (
            <option key={s} value={s}>
              {STATUS_LABEL[s]}
              {stats ? ` (${formatNumber(stats.by_status[s] ?? 0)})` : ""}
            </option>
          ))}
        </select>
        <div className="search">
          <Search size={15} />
          <input
            className="input input--sm"
            placeholder="Phone or lead ID starts with…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            aria-label="Search contacts"
          />
        </div>
        <div className="spacer" />
        {contacts.isFetching && !contacts.isPending && <span className="spinner" style={{ width: 14, height: 14 }} />}
      </div>

      {contacts.isError ? (
        <QueryError error={contacts.error} onRetry={() => contacts.refetch()} />
      ) : !contacts.isPending && items.length === 0 ? (
        <EmptyState icon={<Users size={20} />} title={status || q ? "No matching contacts" : "No contacts yet"}>
          {status || q ? "Try a different filter or search." : "Upload a cohort CSV to add the people this campaign will call."}
        </EmptyState>
      ) : (
        <>
          <div className="table-wrap">
            <table className="table contacts-table">
              <thead>
                <tr>
                  <th>Phone</th>
                  <th>Lead ID</th>
                  <th>Status</th>
                  <th className="num">Attempts</th>
                  <th>Last outcome</th>
                  <th>Next attempt</th>
                  <th>Updated</th>
                </tr>
              </thead>
              <tbody>
                {contacts.isPending ? (
                  <SkeletonRows cols={7} rows={8} />
                ) : (
                  items.map((c) => {
                    const flashing = (flash.get(c.id) ?? 0) > Date.now();
                    const waiting = c.status === "pending" || c.status === "retry_scheduled";
                    return (
                      <tr
                        // Re-mount on change so the highlight animation replays.
                        key={`${c.id}:${c.status}:${c.attempts_made}`}
                        className={`clickable ${flashing ? "flash" : ""} ${selectedId === c.id ? "selected" : ""}`}
                        onClick={() => onSelect(c)}
                      >
                        <td className="mono nowrap">{c.phone_e164}</td>
                        <td className="mono muted">{c.lead_id}</td>
                        <td>
                          <StatusPill status={c.status} kind="contact" />
                        </td>
                        <td className="num">{c.attempts_made}</td>
                        <td>{c.last_outcome ? humanize(c.last_outcome) : <span className="faint">—</span>}</td>
                        <td className="nowrap">
                          <RelativeTime iso={waiting ? c.next_attempt_at : null} dueLabel="Due now" />
                        </td>
                        <td className="muted nowrap">
                          <RelativeTime iso={c.updated_at} />
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
          <div className="pager">
            <span className="tabular">
              {items.length > 0 &&
                `${formatNumber(firstRow)} to ${formatNumber(firstRow + items.length - 1)} of ${formatNumber(total)}`}
            </span>
            <div className="spacer" />
            <Button
              size="sm"
              icon={<ChevronLeft size={14} />}
              disabled={page === 0}
              onClick={() => setCursors((c) => c.slice(0, -1))}
            >
              Previous
            </Button>
            <Button
              size="sm"
              disabled={!nextCursor}
              onClick={() => nextCursor && setCursors((c) => [...c, nextCursor])}
            >
              Next <ChevronRight size={14} />
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
