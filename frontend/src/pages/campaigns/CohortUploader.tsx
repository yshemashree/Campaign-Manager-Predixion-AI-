import { useState, type DragEvent, type ReactNode } from "react";
import { Download, FileCheck2, FileSpreadsheet, UploadCloud } from "lucide-react";
import type { Agent, CohortUploadResult } from "../../api/types";
import { Button } from "../../components/Button";
import { Banner, ErrorBanner } from "../../components/Feedback";
import { formatNumber } from "../../lib/format";
import { saveFile } from "../../lib/download";
import { useSampleCsvDownload } from "../agents/SampleCsvButton";

export interface CohortDraft {
  file: File | null;
  /** Dry-run result for the current file. */
  check: CohortUploadResult | null;
  skipInvalid: boolean;
}

export const EMPTY_COHORT: CohortDraft = { file: null, check: null, skipInvalid: false };

/** Valid rows that will actually be added: not on the DND list and not already in the campaign. */
export function importableRows(r: CohortUploadResult): number {
  return Math.max(r.rows_valid - r.duplicates_existing - (r.dnd_skipped ?? 0), 0);
}

export function cohortReady(d: CohortDraft): boolean {
  const r = d.check;
  if (!d.file || !r) return false;
  if (r.header_errors.length > 0) return false;
  if (r.rows_rejected > 0 && !d.skipInvalid) return false;
  return importableRows(r) > 0;
}

interface UploaderProps {
  value: CohortDraft;
  onChange: (draft: CohortDraft) => void;
  agent?: Pick<Agent, "id" | "name">;
  /** Validates the file on the server without importing anything. */
  runDryRun: (file: File) => Promise<CohortUploadResult>;
  note?: ReactNode;
}

export function CohortUploader({ value, onChange, agent, runDryRun, note }: UploaderProps) {
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [dragging, setDragging] = useState(false);
  const sample = useSampleCsvDownload();

  function pickFile(file: File | null) {
    setError(null);
    onChange({ file, check: null, skipInvalid: false });
  }

  async function check() {
    if (!value.file) return;
    setChecking(true);
    setError(null);
    try {
      const result = await runDryRun(value.file);
      onChange({ ...value, check: result });
    } catch (err) {
      setError(err);
    } finally {
      setChecking(false);
    }
  }

  function onDrop(e: DragEvent<HTMLLabelElement>) {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files[0];
    if (file) pickFile(file);
  }

  const result = value.check;

  return (
    <div className="stack">
      <label
        className={`dropzone ${dragging ? "dropzone--active" : ""} ${value.file ? "dropzone--filled" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
      >
        <input
          type="file"
          accept=".csv,text/csv"
          className="sr-only"
          onChange={(e) => {
            pickFile(e.target.files?.[0] ?? null);
            e.target.value = "";
          }}
        />
        {value.file ? (
          <>
            <FileSpreadsheet size={22} className="dropzone__icon" />
            <div>
              <div className="cell-title">{value.file.name}</div>
              <div className="cell-sub">{formatBytes(value.file.size)} · click or drop to choose another file</div>
            </div>
          </>
        ) : (
          <>
            <UploadCloud size={22} className="dropzone__icon" />
            <div>
              <div className="cell-title">Choose a CSV file or drop it here</div>
              <div className="cell-sub">
                Columns: <span className="mono">phone_number</span>, <span className="mono">lead_id</span> (optional)
                and one per agent variable. UTF-8, up to 20 MB.
              </div>
            </div>
          </>
        )}
      </label>

      <div className="row-wrap">
        <Button
          variant={result ? "secondary" : "primary"}
          icon={<FileCheck2 size={15} />}
          disabled={!value.file}
          loading={checking}
          onClick={check}
        >
          {result ? "Check again" : "Check file"}
        </Button>
        {agent && (
          <button type="button" className="link-btn" onClick={() => sample.download(agent)} disabled={sample.busy}>
            <Download size={14} />
            Download a sample CSV for {agent.name}
          </button>
        )}
        <div className="spacer" />
        {note && <span className="muted small">{note}</span>}
      </div>

      {error != null && <ErrorBanner error={error} />}

      {result && (
        <>
          <CohortReport result={result} filename={value.file?.name} />
          {result.header_errors.length === 0 && result.rows_rejected > 0 && (
            <label className="check">
              <input
                type="checkbox"
                checked={value.skipInvalid}
                onChange={(e) => onChange({ ...value, skipInvalid: e.target.checked })}
              />
              Skip the {formatNumber(result.rows_rejected)} invalid rows and import the rest
            </label>
          )}
          <ReadinessBanner draft={value} />
        </>
      )}
    </div>
  );
}

function ReadinessBanner({ draft }: { draft: CohortDraft }) {
  const r = draft.check!;
  if (r.header_errors.length > 0) {
    return (
      <Banner tone="error" title="The file's columns don't match this agent">
        Fix the header row and check the file again.
      </Banner>
    );
  }
  if (r.rows_rejected > 0 && !draft.skipInvalid) {
    return (
      <Banner tone="warning" title={`${formatNumber(r.rows_rejected)} rows have problems`}>
        Uploads are strict by default: fix the rows and check again, or tick the box above to import only the valid
        ones.
      </Banner>
    );
  }
  const n = importableRows(r);
  if (n === 0) {
    return (
      <Banner tone="warning" title="Nothing new to import">
        Every valid number in this file is already in the campaign or on the Do Not Disturb list.
      </Banner>
    );
  }
  return (
    <Banner tone="success" title={`Ready to import ${formatNumber(n)} contacts`}>
      {draft.skipInvalid && r.rows_rejected > 0 && `${formatNumber(r.rows_rejected)} invalid rows will be skipped. `}
      {r.duplicates_existing > 0 && `${formatNumber(r.duplicates_existing)} numbers already in the campaign will be left as they are. `}
      {r.dnd_skipped > 0 && `${formatNumber(r.dnd_skipped)} numbers on the Do Not Disturb list will not be called.`}
    </Banner>
  );
}

export function CohortReport({ result, filename }: { result: CohortUploadResult; filename?: string }) {
  const stats: { label: string; value: number; tone?: "good" | "bad" }[] = [
    { label: "Rows in file", value: result.rows_total },
    { label: "Valid", value: result.rows_valid, tone: "good" },
    { label: "Rejected", value: result.rows_rejected, tone: result.rows_rejected ? "bad" : undefined },
    { label: "Duplicates in file", value: result.duplicates_in_file },
    { label: "Already in campaign", value: result.duplicates_existing },
    { label: "Do Not Disturb", value: result.dnd_skipped ?? 0 },
  ];

  function downloadReport() {
    if (!result.error_report_csv) return;
    const base = (filename ?? "cohort").replace(/\.csv$/i, "");
    saveFile(result.error_report_csv, `${base}-errors.csv`);
  }

  return (
    <div className="report">
      <div className="report__stats">
        {stats.map((s) => (
          <div key={s.label} className="report__stat">
            <div className="kpi__label">{s.label}</div>
            <div className={`report__value ${s.tone ? `report__value--${s.tone}` : ""}`}>{formatNumber(s.value)}</div>
          </div>
        ))}
      </div>

      {result.header_errors.length > 0 && (
        <div className="report__section">
          <div className="section-title">Header problems</div>
          <ul className="report__list">
            {result.header_errors.map((h, i) => (
              <li key={i}>{h}</li>
            ))}
          </ul>
        </div>
      )}

      {result.errors.length > 0 && (
        <div className="report__section">
          <div className="row" style={{ marginBottom: 8 }}>
            <div className="section-title" style={{ margin: 0 }}>
              {result.rows_rejected > result.errors.length
                ? `First ${result.errors.length} problems`
                : `${result.errors.length} problem${result.errors.length === 1 ? "" : "s"}`}
            </div>
            <div className="spacer" />
            {result.error_report_csv && (
              <Button size="sm" icon={<Download size={14} />} onClick={downloadReport}>
                Download error report
              </Button>
            )}
          </div>
          <div className="report__errors">
            <table className="table table--compact">
              <thead>
                <tr>
                  <th style={{ width: 70 }}>Row</th>
                  <th style={{ width: 160 }}>Column</th>
                  <th>Problem</th>
                </tr>
              </thead>
              <tbody>
                {result.errors.map((e, i) => (
                  <tr key={i}>
                    <td className="tabular">{e.row}</td>
                    <td className="mono">{e.column}</td>
                    <td>{e.message}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
