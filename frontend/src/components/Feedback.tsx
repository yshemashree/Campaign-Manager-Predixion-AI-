import type { ReactNode } from "react";
import { AlertCircle, AlertTriangle, CheckCircle2, Info } from "lucide-react";
import { ApiError } from "../api/client";

export function Spinner({ label }: { label?: string }) {
  return <span className="spinner" role="status" aria-label={label ?? "Loading"} />;
}

export function PageSpinner() {
  return (
    <div className="center-fill">
      <Spinner />
    </div>
  );
}

export function SkeletonRows({ rows = 5, cols = 5 }: { rows?: number; cols?: number }) {
  return (
    <>
      {Array.from({ length: rows }, (_, r) => (
        <tr key={r}>
          {Array.from({ length: cols }, (_, c) => (
            <td key={c}>
              <span className="skeleton" style={{ width: `${45 + ((r * 7 + c * 13) % 45)}%` }} />
            </td>
          ))}
        </tr>
      ))}
    </>
  );
}

interface EmptyStateProps {
  icon?: ReactNode;
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}

export function EmptyState({ icon, title, children, action }: EmptyStateProps) {
  return (
    <div className="empty">
      {icon && <div className="empty__icon">{icon}</div>}
      <h3>{title}</h3>
      {children && <p>{children}</p>}
      {action}
    </div>
  );
}

type Tone = "error" | "warning" | "info" | "success";

const TONE_ICON: Record<Tone, ReactNode> = {
  error: <AlertCircle size={16} />,
  warning: <AlertTriangle size={16} />,
  info: <Info size={16} />,
  success: <CheckCircle2 size={16} />,
};

export function Banner({ tone, title, children }: { tone: Tone; title?: ReactNode; children?: ReactNode }) {
  return (
    <div className={`banner banner--${tone}`} role={tone === "error" ? "alert" : "status"}>
      {TONE_ICON[tone]}
      <div>
        {title && <div className="banner__title">{title}</div>}
        {children}
      </div>
    </div>
  );
}

interface ErrorBannerProps {
  error: unknown;
  /** Field paths shown next to inputs; errors for these are not repeated in the banner. */
  shownFields?: string[];
}

/** The API's `detail`, plus any field errors that have no input on screen to sit under. */
export function ErrorBanner({ error, shownFields = [] }: ErrorBannerProps) {
  if (!error) return null;
  if (!(error instanceof ApiError)) {
    return <Banner tone="error" title="Something went wrong">{String((error as Error).message ?? error)}</Banner>;
  }
  const shown = new Set(shownFields);
  const extra = error.errors.filter((e) => !shown.has(e.field));
  return (
    <Banner tone="error" title={error.detail}>
      {extra.length > 0 && (
        <ul>
          {extra.map((e, i) => (
            <li key={i}>
              {e.field && <strong>{e.field}: </strong>}
              {e.message}
            </li>
          ))}
        </ul>
      )}
    </Banner>
  );
}

export function QueryError({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message = error instanceof ApiError ? error.detail : "Could not load this data.";
  return (
    <div className="empty">
      <div className="empty__icon" style={{ background: "var(--red-soft)", color: "var(--red)" }}>
        <AlertCircle size={20} />
      </div>
      <h3>Couldn't load this</h3>
      <p>{message}</p>
      {onRetry && (
        <button className="btn" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  );
}
