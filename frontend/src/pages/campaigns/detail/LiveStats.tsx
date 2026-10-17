import { Clock, MoonStar } from "lucide-react";
import type { Campaign, CampaignStats } from "../../../api/types";
import { ProgressBar } from "../../../components/ProgressBar";
import { count, finishedCount, segments, STATUS_COLOURS } from "../../../lib/contactStatus";
import { formatDateTime, formatNumber, formatZoneDayTime, formatZoneTime, percent } from "../../../lib/format";
import type { LiveMode } from "./useCampaignLive";

export function LiveIndicator({ mode }: { mode: LiveMode }) {
  const text = { live: "Live", polling: "Refreshing every 3 s", connecting: "Connecting" }[mode];
  const title =
    mode === "polling" ? "The live stream isn't available, so the numbers are refreshed every few seconds." : undefined;
  return (
    <span className={`live ${mode === "live" ? "live--on" : ""} ${mode === "polling" ? "live--polling" : ""}`} title={title}>
      <span className="live__dot" />
      {text}
    </span>
  );
}

/** Plain-language calling window state, e.g. "Calling window open, closes at 18:00 IST". */
export function WindowStatus({ campaign, stats }: { campaign: Campaign; stats?: CampaignStats }) {
  if (!stats || campaign.status === "completed" || campaign.status === "stopped") return null;
  const tz = campaign.calling_window.timezone;
  if (stats.in_window && stats.window_closes_at) {
    return (
      <span className="window-status window-status--open">
        <Clock size={14} />
        Calling window open, closes at {formatZoneTime(stats.window_closes_at, tz)}
      </span>
    );
  }
  if (stats.next_window_opens_at) {
    return (
      <span className="window-status">
        <MoonStar size={14} />
        Outside calling window, next opens {formatZoneDayTime(stats.next_window_opens_at, tz)}
      </span>
    );
  }
  return (
    <span className="window-status">
      <MoonStar size={14} />
      No calling window left before the campaign ends
    </span>
  );
}

interface Kpi {
  label: string;
  value: number;
  colour?: string;
  sub?: string;
}

export function LiveStats({ campaign, stats, mode }: { campaign: Campaign; stats?: CampaignStats; mode: LiveMode }) {
  const total = stats?.total ?? 0;
  const done = finishedCount(stats?.by_status);
  const kpis: Kpi[] = [
    { label: "Total contacts", value: total },
    { label: "Pending", value: count(stats?.by_status, "pending"), colour: STATUS_COLOURS.pending },
    {
      label: "Dialing / in progress",
      value: count(stats?.by_status, "dialing") + count(stats?.by_status, "in_progress"),
      colour: STATUS_COLOURS.in_flight,
    },
    { label: "Completed", value: count(stats?.by_status, "completed"), colour: STATUS_COLOURS.completed },
    { label: "Retry scheduled", value: count(stats?.by_status, "retry_scheduled"), colour: STATUS_COLOURS.retry_scheduled },
    { label: "Failed", value: count(stats?.by_status, "failed"), colour: STATUS_COLOURS.failed },
    { label: "Cancelled", value: count(stats?.by_status, "cancelled"), colour: STATUS_COLOURS.cancelled },
    {
      label: "Attempts",
      value: stats?.attempts_total ?? 0,
      sub: total ? `${(Math.round(((stats?.attempts_total ?? 0) / total) * 10) / 10).toFixed(1)} per contact` : undefined,
    },
  ];
  const segs = segments(stats?.by_status);

  return (
    <div className="card">
      <div className="card__header">
        <h2>Progress</h2>
        <LiveIndicator mode={mode} />
        <div className="spacer" />
        <WindowStatus campaign={campaign} stats={stats} />
      </div>
      <div className="kpi-grid">
        {kpis.map((k) => (
          <div className="kpi" key={k.label}>
            <div className="kpi__label">
              {k.colour && <span className="kpi__swatch" style={{ background: k.colour }} />}
              {k.label}
            </div>
            <div className="kpi__value">{stats ? formatNumber(k.value) : <span className="skeleton" style={{ width: 48, height: 22 }} />}</div>
            {k.sub && <div className="kpi__sub">{k.sub}</div>}
          </div>
        ))}
      </div>
      <div className="card__body" style={{ paddingTop: 16, paddingBottom: 16 }}>
        <div className="row" style={{ marginBottom: 8 }}>
          <span className="small">
            <strong className="tabular">{percent(done, total)}%</strong>
            <span className="muted">
              {" "}
              finished ({formatNumber(done)} of {formatNumber(total)} contacts)
            </span>
          </span>
          <div className="spacer" />
          <span className="small muted">
            {campaign.started_at && `Started ${formatDateTime(campaign.started_at)}`}
            {campaign.finished_at && ` · Finished ${formatDateTime(campaign.finished_at)}`}
          </span>
        </div>
        <ProgressBar segments={segs} total={total} />
        <div className="legend" style={{ marginTop: 10 }}>
          {segs
            .filter((s) => s.key !== "pending")
            .map((s) => (
              <span key={s.key} className="legend__item">
                <span className="kpi__swatch" style={{ background: s.colour }} />
                {s.label}
              </span>
            ))}
          <span className="legend__item">
            <span className="kpi__swatch" style={{ background: "var(--surface-3)", border: "1px solid var(--border)" }} />
            Pending
          </span>
        </div>
      </div>
    </div>
  );
}
