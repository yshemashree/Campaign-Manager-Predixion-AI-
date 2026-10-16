import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, PhoneOff, Plus, Search, Trash2, Upload } from "lucide-react";
import { dndApi } from "../api/endpoints";
import { keys, useDnd } from "../api/queries";
import type { DndAddResult, DndEntry } from "../api/types";
import { useAuth, useUser } from "../auth/AuthContext";
import { Button } from "../components/Button";
import { Banner, EmptyState, ErrorBanner, QueryError, SkeletonRows } from "../components/Feedback";
import { Field } from "../components/Field";
import { ConfirmDialog, Modal } from "../components/Overlay";
import { PageHeader } from "../components/PageHeader";
import { RelativeTime } from "../components/RelativeTime";
import { useToast } from "../components/Toast";
import { formatNumber } from "../lib/format";
import { useWorkspace } from "../workspace/WorkspaceContext";

const PAGE_SIZE = 50;

export function DndPage() {
  const user = useUser();
  const { isAdmin, isSuperadmin } = useAuth();
  const { orgs } = useWorkspace();
  const [pickedOrg, setPickedOrg] = useState("");
  const orgId = user.org_id ?? (pickedOrg || [...orgs.keys()][0] || null);

  const [search, setSearch] = useState("");
  const [term, setTerm] = useState("");
  const [cursors, setCursors] = useState<(string | undefined)[]>([undefined]);
  const page = cursors.length - 1;
  useEffect(() => {
    const t = setTimeout(() => {
      setTerm(search.trim());
      setCursors([undefined]);
    }, 300);
    return () => clearTimeout(t);
  }, [search]);
  useEffect(() => setCursors([undefined]), [orgId]);

  const list = useDnd(orgId, { search: term || undefined, cursor: cursors[page], limit: PAGE_SIZE });
  const [dialog, setDialog] = useState<"paste" | "upload" | null>(null);
  const [removing, setRemoving] = useState<DndEntry | null>(null);
  const queryClient = useQueryClient();
  const toast = useToast();

  const remove = useMutation({
    mutationFn: (entry: DndEntry) => dndApi.remove(orgId!, entry.phone_e164),
    onSuccess: (_, entry) => {
      queryClient.invalidateQueries({ queryKey: keys.dnd(orgId!) });
      toast.success("Removed from Do Not Disturb", entry.phone_e164);
      setRemoving(null);
    },
    onError: (err) => {
      toast.apiError("Couldn't remove the number", err);
      setRemoving(null);
    },
  });

  const items = list.data?.items ?? [];
  const total = list.data?.total ?? 0;
  const firstRow = page * PAGE_SIZE + 1;

  return (
    <>
      <PageHeader
        title="Do Not Disturb"
        description="Numbers on this list are never called by any campaign in the organisation. They're skipped when recipients are uploaded."
        actions={
          isAdmin && (
            <>
              <Button icon={<Upload size={15} />} onClick={() => setDialog("upload")}>
                Upload CSV
              </Button>
              <Button variant="primary" icon={<Plus size={16} />} onClick={() => setDialog("paste")}>
                Add numbers
              </Button>
            </>
          )
        }
      />
      <div className="card">
        <div className="toolbar">
          {isSuperadmin && (
            <select
              className="select select--sm"
              style={{ width: 220 }}
              aria-label="Organization"
              value={orgId ?? ""}
              onChange={(e) => setPickedOrg(e.target.value)}
            >
              {[...orgs.values()].map((o) => (
                <option key={o.id} value={o.id}>
                  {o.name}
                </option>
              ))}
            </select>
          )}
          <div className="search">
            <Search size={15} />
            <input
              className="input input--sm"
              placeholder="Search numbers"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              aria-label="Search the Do Not Disturb list"
            />
          </div>
          <div className="spacer" />
          {list.data && (
            <span className="muted small tabular">
              {formatNumber(total)} number{total === 1 ? "" : "s"}
            </span>
          )}
        </div>
        {list.isError ? (
          <QueryError error={list.error} onRetry={() => list.refetch()} />
        ) : !list.isPending && items.length === 0 ? (
          <EmptyState icon={<PhoneOff size={20} />} title={term ? "No matching numbers" : "The list is empty"}>
            {term
              ? "Try a different search."
              : isAdmin
                ? "Add numbers that asked not to be called. They are skipped in every campaign."
                : "No numbers are blocked yet."}
          </EmptyState>
        ) : (
          <>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Phone number</th>
                    <th>Reason</th>
                    <th>Added</th>
                    {isAdmin && (
                      <th style={{ width: 60 }}>
                        <span className="sr-only">Actions</span>
                      </th>
                    )}
                  </tr>
                </thead>
                <tbody>
                  {list.isPending ? (
                    <SkeletonRows cols={isAdmin ? 4 : 3} rows={5} />
                  ) : (
                    items.map((d) => (
                      <tr key={d.id}>
                        <td className="mono">{d.phone_e164}</td>
                        <td>{d.reason || <span className="faint">—</span>}</td>
                        <td className="muted nowrap">
                          <RelativeTime iso={d.created_at} />
                        </td>
                        {isAdmin && (
                          <td className="num">
                            <Button
                              size="sm"
                              variant="ghost"
                              aria-label={`Remove ${d.phone_e164}`}
                              icon={<Trash2 size={14} />}
                              onClick={() => setRemoving(d)}
                            />
                          </td>
                        )}
                      </tr>
                    ))
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
              <Button size="sm" icon={<ChevronLeft size={14} />} disabled={page === 0} onClick={() => setCursors((c) => c.slice(0, -1))}>
                Previous
              </Button>
              <Button
                size="sm"
                disabled={!list.data?.next_cursor}
                onClick={() => list.data?.next_cursor && setCursors((c) => [...c, list.data!.next_cursor!])}
              >
                Next <ChevronRight size={14} />
              </Button>
            </div>
          </>
        )}
      </div>

      {dialog && orgId && <AddNumbersModal orgId={orgId} mode={dialog} onClose={() => setDialog(null)} />}
      {removing && (
        <ConfirmDialog
          title="Remove from Do Not Disturb?"
          confirmLabel="Remove"
          danger
          loading={remove.isPending}
          onConfirm={() => remove.mutate(removing)}
          onClose={() => setRemoving(null)}
        >
          <p>
            <span className="mono">{removing.phone_e164}</span> can be called again by campaigns that include it.
          </p>
        </ConfirmDialog>
      )}
    </>
  );
}

function AddNumbersModal({ orgId, mode, onClose }: { orgId: string; mode: "paste" | "upload"; onClose: () => void }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [text, setText] = useState("");
  const [reason, setReason] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<DndAddResult | null>(null);

  const numbers = text
    .split(/[\s,;]+/)
    .map((n) => n.trim())
    .filter(Boolean);

  const add = useMutation({
    mutationFn: () => (mode === "paste" ? dndApi.add(orgId, numbers, reason.trim()) : dndApi.upload(orgId, file!)),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: keys.dnd(orgId) });
      setResult(res);
      if (res.invalid.length === 0) {
        toast.success("Do Not Disturb updated", `${formatNumber(res.added)} added.`);
        onClose();
      }
    },
  });

  const canSubmit = mode === "paste" ? numbers.length > 0 : !!file;

  return (
    <Modal
      title={mode === "paste" ? "Add numbers to Do Not Disturb" : "Upload a Do Not Disturb CSV"}
      description={
        mode === "paste"
          ? "One per line, or separated by commas. Local numbers are read as Indian numbers."
          : "A CSV with a phone_number column and an optional reason column."
      }
      onClose={onClose}
      onSubmit={() => canSubmit && add.mutate()}
      footer={
        <>
          <Button onClick={onClose}>{result ? "Close" : "Cancel"}</Button>
          <Button type="submit" variant="primary" disabled={!canSubmit} loading={add.isPending}>
            {mode === "paste" ? `Add ${numbers.length || ""} number${numbers.length === 1 ? "" : "s"}` : "Upload"}
          </Button>
        </>
      }
    >
      <div className="stack">
        {add.isError && <ErrorBanner error={add.error} />}
        {result && (
          <Banner tone="warning" title={`${formatNumber(result.added)} added, ${formatNumber(result.already_listed)} already listed`}>
            {result.invalid.length} not recognised as phone numbers:{" "}
            <span className="mono">{result.invalid.slice(0, 10).join(", ")}</span>
            {result.invalid.length > 10 && ` and ${result.invalid.length - 10} more`}
          </Banner>
        )}
        {mode === "paste" ? (
          <>
            <Field label="Phone numbers">
              <textarea
                className="textarea mono"
                rows={6}
                placeholder={"+919876543210\n+919812345678"}
                value={text}
                onChange={(e) => setText(e.target.value)}
                autoFocus
              />
            </Field>
            <Field label="Reason" optional hint="Shown in the list, e.g. 'Asked not to be called'.">
              <input className="input" value={reason} onChange={(e) => setReason(e.target.value)} />
            </Field>
          </>
        ) : (
          <Field label="CSV file">
            <input
              className="input"
              type="file"
              accept=".csv,text/csv"
              style={{ paddingTop: 6 }}
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </Field>
        )}
      </div>
    </Modal>
  );
}
