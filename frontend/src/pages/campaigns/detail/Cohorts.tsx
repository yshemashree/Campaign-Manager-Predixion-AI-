import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Download, FileSpreadsheet, Upload } from "lucide-react";
import { cohortApi } from "../../../api/endpoints";
import { keys, useCohorts } from "../../../api/queries";
import type { Agent, Campaign, Cohort } from "../../../api/types";
import { Button } from "../../../components/Button";
import { EmptyState, ErrorBanner, QueryError, SkeletonRows } from "../../../components/Feedback";
import { Modal } from "../../../components/Overlay";
import { useToast } from "../../../components/Toast";
import { saveFile } from "../../../lib/download";
import { formatDateTime, formatNumber } from "../../../lib/format";
import { CohortUploader, EMPTY_COHORT, cohortReady, importableRows, type CohortDraft } from "../CohortUploader";

const UPLOAD_ALLOWED = new Set(["draft", "scheduled", "running", "paused"]);

export function canUploadContacts(campaign: Campaign): boolean {
  return UPLOAD_ALLOWED.has(campaign.status);
}

export function CohortsSection({ campaign, onUpload }: { campaign: Campaign; onUpload: () => void }) {
  const cohorts = useCohorts(campaign.id);
  const toast = useToast();
  const [downloading, setDownloading] = useState<string | null>(null);

  async function downloadErrors(cohort: Cohort) {
    setDownloading(cohort.id);
    try {
      const { blob, filename } = await cohortApi.errorReport(cohort.id);
      saveFile(blob, filename ?? `errors-${cohort.filename}`);
    } catch (err) {
      toast.apiError("Couldn't download the error report", err);
    } finally {
      setDownloading(null);
    }
  }

  const uploadButton = canUploadContacts(campaign) && (
    <Button variant="primary" size="sm" icon={<Upload size={14} />} onClick={onUpload}>
      Upload more contacts
    </Button>
  );

  return (
    <div>
      <div className="toolbar">
        <span className="muted small">Every CSV uploaded to this campaign, newest first.</span>
        <div className="spacer" />
        {uploadButton}
      </div>
      {cohorts.isError ? (
        <QueryError error={cohorts.error} onRetry={() => cohorts.refetch()} />
      ) : cohorts.data?.length === 0 ? (
        <EmptyState icon={<FileSpreadsheet size={20} />} title="No uploads yet" action={uploadButton}>
          Upload a CSV with a phone number per row, plus the agent's variables.
        </EmptyState>
      ) : (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>File</th>
                <th>Uploaded</th>
                <th className="num">Rows</th>
                <th className="num">Imported</th>
                <th className="num">Rejected</th>
                <th className="num">Duplicates</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {cohorts.isPending ? (
                <SkeletonRows cols={7} rows={2} />
              ) : (
                cohorts.data.map((c) => (
                  <tr key={c.id}>
                    <td className="cell-title">{c.filename}</td>
                    <td className="muted nowrap">{formatDateTime(c.created_at)}</td>
                    <td className="num">{formatNumber(c.rows_total)}</td>
                    <td className="num">{formatNumber(c.rows_accepted)}</td>
                    <td className={`num ${c.rows_rejected ? "error-text" : ""}`}>{formatNumber(c.rows_rejected)}</td>
                    <td className="num">{formatNumber(c.rows_duplicate)}</td>
                    <td className="num">
                      {c.rows_rejected > 0 && (
                        <Button
                          size="sm"
                          variant="ghost"
                          icon={<Download size={14} />}
                          loading={downloading === c.id}
                          onClick={() => downloadErrors(c)}
                        >
                          Error report
                        </Button>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export function UploadContactsModal({
  campaign,
  agent,
  onClose,
}: {
  campaign: Campaign;
  agent?: Agent;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [draft, setDraft] = useState<CohortDraft>(EMPTY_COHORT);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function importContacts() {
    if (!draft.file) return;
    setImporting(true);
    setError(null);
    try {
      const result = await cohortApi.upload(campaign.id, draft.file, { dryRun: false, skipInvalid: draft.skipInvalid });
      if (!result.accepted) {
        setDraft({ ...draft, check: result });
        toast.error("Nothing was imported", "Review the problems in the report.");
        return;
      }
      queryClient.invalidateQueries({ queryKey: keys.cohorts(campaign.id) });
      queryClient.invalidateQueries({ queryKey: keys.contacts(campaign.id) });
      queryClient.invalidateQueries({ queryKey: keys.stats(campaign.id), exact: true });
      toast.success("Contacts imported", `${formatNumber(result.cohort?.rows_accepted ?? 0)} new contacts added.`);
      onClose();
    } catch (err) {
      setError(err);
    } finally {
      setImporting(false);
    }
  }

  const ready = cohortReady(draft);

  return (
    <Modal
      wide
      title="Upload contacts"
      description="Check the file first. Nothing is imported until you confirm."
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" disabled={!ready} loading={importing} onClick={importContacts}>
            {ready && draft.check ? `Import ${formatNumber(importableRows(draft.check))} contacts` : "Import contacts"}
          </Button>
        </>
      }
    >
      <div className="stack">
        {error != null && <ErrorBanner error={error} />}
        <CohortUploader
          value={draft}
          onChange={setDraft}
          agent={agent}
          runDryRun={(file) => cohortApi.upload(campaign.id, file, { dryRun: true, skipInvalid: false })}
        />
      </div>
    </Modal>
  );
}
