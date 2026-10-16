import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Ban } from "lucide-react";
import { contactApi } from "../../../api/endpoints";
import { keys, useContact } from "../../../api/queries";
import { Button } from "../../../components/Button";
import { RelativeTime } from "../../../components/RelativeTime";
import { useToast } from "../../../components/Toast";
import type { Attempt, Contact } from "../../../api/types";
import { QueryError, Spinner } from "../../../components/Feedback";
import { ConfirmDialog, Drawer } from "../../../components/Overlay";
import { StatusPill } from "../../../components/StatusPill";
import { formatCompact, formatDateTime, formatDuration, humanize } from "../../../lib/format";

const FINAL_REASONS: Record<string, string> = {
  rejected: "Sarvam refused the call request",
  max_attempts_reached: "Reached the maximum number of attempts",
  campaign_stopped: "The campaign was stopped",
  campaign_ended: "The campaign ended before it could be called again",
  campaign_completed: "The campaign completed",
  cancelled_by_user: "Cancelled by a user",
};

export function ContactDrawer({ contact, onClose }: { contact: Contact; onClose: () => void }) {
  const detail = useContact(contact.id);
  const c = detail.data ?? contact;
  const queryClient = useQueryClient();
  const toast = useToast();
  const [confirming, setConfirming] = useState(false);

  const cancel = useMutation({
    mutationFn: () => contactApi.cancel(c.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: keys.contact(c.id), exact: true });
      queryClient.invalidateQueries({ queryKey: keys.contacts(c.campaign_id) });
      queryClient.invalidateQueries({ queryKey: keys.stats(c.campaign_id), exact: true });
      toast.success("Contact cancelled", `${c.phone_e164} won't be called again.`);
      setConfirming(false);
    },
    onError: (err) => {
      toast.apiError("Couldn't cancel the contact", err);
      setConfirming(false);
    },
  });
  const waiting = c.status === "pending" || c.status === "retry_scheduled";
  const variables = Object.entries(c.variables ?? {});

  return (
    <Drawer
      title={<span className="mono">{c.phone_e164}</span>}
      subtitle={
        <div className="row">
          <StatusPill status={c.status} kind="contact" />
          <span className="muted small">Lead {c.lead_id}</span>
        </div>
      }
      onClose={onClose}
    >
      <div className="stack" style={{ gap: 24 }}>
        <section>
          <h3 className="section-title">Overview</h3>
          <dl className="kv">
            <dt>Attempts made</dt>
            <dd className="tabular">{c.attempts_made}</dd>
            <dt>Last outcome</dt>
            <dd>{c.last_outcome ? humanize(c.last_outcome) : "—"}</dd>
            {c.final_reason && (
              <>
                <dt>Final reason</dt>
                <dd>{FINAL_REASONS[c.final_reason] ?? humanize(c.final_reason)}</dd>
              </>
            )}
            {waiting && (
              <>
                <dt>Next attempt</dt>
                <dd>
                  <RelativeTime iso={c.next_attempt_at} dueLabel="Due now" />
                </dd>
              </>
            )}
            <dt>Last updated</dt>
            <dd>{formatDateTime(c.updated_at)}</dd>
          </dl>
          {waiting && (
            <div style={{ marginTop: 14 }}>
              <Button variant="danger-outline" size="sm" icon={<Ban size={14} />} onClick={() => setConfirming(true)}>
                Cancel contact
              </Button>
            </div>
          )}
        </section>

        <section>
          <h3 className="section-title">Variables</h3>
          {variables.length === 0 ? (
            <p className="muted small">No variables for this contact.</p>
          ) : (
            <div className="fieldset" style={{ padding: 0, overflow: "hidden" }}>
              <table className="table table--compact">
                <tbody>
                  {variables.map(([k, v]) => (
                    <tr key={k}>
                      <td className="mono muted" style={{ width: "40%" }}>
                        {k}
                      </td>
                      <td style={{ overflowWrap: "anywhere" }}>{v === null || v === "" ? <span className="faint">empty</span> : String(v)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <section>
          <h3 className="section-title">Call attempts</h3>
          {detail.isPending ? (
            <Spinner />
          ) : detail.isError ? (
            <QueryError error={detail.error} onRetry={() => detail.refetch()} />
          ) : detail.data.attempts.length === 0 ? (
            <p className="muted small">Not called yet.</p>
          ) : (
            <ol className="timeline">
              {[...detail.data.attempts].reverse().map((a) => (
                <AttemptItem key={a.id} attempt={a} />
              ))}
            </ol>
          )}
        </section>
      </div>
      {confirming && (
        <ConfirmDialog
          title="Cancel this contact?"
          confirmLabel="Cancel contact"
          danger
          loading={cancel.isPending}
          onConfirm={() => cancel.mutate()}
          onClose={() => setConfirming(false)}
        >
          <p>
            <span className="mono">{c.phone_e164}</span> won't be called again in this campaign. Its call history is
            kept.
          </p>
        </ConfirmDialog>
      )}
    </Drawer>
  );
}

function AttemptItem({ attempt: a }: { attempt: Attempt }) {
  return (
    <li className={`timeline__item timeline__item--${a.status}`}>
      <span className="timeline__dot" />
      <div className="timeline__body">
        <div className="row">
          <strong>Attempt {a.attempt_no}</strong>
          <StatusPill status={a.status} kind="attempt" />
          <div className="spacer" />
          <span className="muted small">{formatCompact(a.created_at)}</span>
        </div>
        <dl className="kv small" style={{ marginTop: 8 }}>
          {a.from_number && (
            <>
              <dt>From</dt>
              <dd className="mono">{a.from_number}</dd>
            </>
          )}
          {a.dispatched_at && (
            <>
              <dt>Sent</dt>
              <dd>{formatCompact(a.dispatched_at)}</dd>
            </>
          )}
          {a.ended_at && (
            <>
              <dt>Ended</dt>
              <dd>{formatCompact(a.ended_at)}</dd>
            </>
          )}
          {a.duration_s !== null && (
            <>
              <dt>Duration</dt>
              <dd>{formatDuration(a.duration_s)}</dd>
            </>
          )}
          {a.http_status !== null && (
            <>
              <dt>HTTP status</dt>
              <dd className="tabular">{a.http_status}</dd>
            </>
          )}
          {a.failure_reason && (
            <>
              <dt>Reason</dt>
              <dd className="error-text">{a.failure_reason}</dd>
            </>
          )}
          {a.provider_attempt_id && (
            <>
              <dt>Provider ID</dt>
              <dd className="mono faint">{a.provider_attempt_id}</dd>
            </>
          )}
        </dl>
      </div>
    </li>
  );
}
