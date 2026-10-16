import type { ReactNode } from "react";
import type { Agent, CampaignSettings, Connection, RetryOutcome } from "../../api/types";
import { RETRY_OUTCOMES } from "../../api/types";
import { describeDays, formatDateTime, zoneAbbreviation } from "../../lib/format";
import "./wizard.css";

const OUTCOME_LABEL: Record<RetryOutcome, string> = {
  busy: "Busy",
  no_answer: "No answer",
  short_call: "Short call",
  failed: "Failed",
};

function delayText(seconds: number): string {
  if (seconds % 3600 === 0 && seconds >= 3600) return `${seconds / 3600} h`;
  if (seconds % 60 === 0) return `${seconds / 60} min`;
  return `${seconds} s`;
}

interface Props {
  settings: CampaignSettings;
  agent?: Agent;
  connection?: Connection;
  /** Shows "Edit" links that jump back to a wizard step. */
  onEdit?: (step: "agent" | "schedule") => void;
}

export function CampaignSummary({ settings, agent, connection, onEdit }: Props) {
  const rp = settings.retry_policy;
  const cw = settings.calling_window;
  const numbers = settings.caller_numbers ?? connection?.caller_numbers ?? [];

  const section = (title: string, step: "agent" | "schedule", rows: [string, ReactNode][]) => (
    <div className="summary">
      <div className="summary__head">
        <h3>{title}</h3>
        {onEdit && (
          <button type="button" className="link-btn" onClick={() => onEdit(step)}>
            Edit
          </button>
        )}
      </div>
      <dl className="kv">
        {rows.map(([k, v]) => (
          <div key={k} style={{ display: "contents" }}>
            <dt>{k}</dt>
            <dd>{v}</dd>
          </div>
        ))}
      </dl>
    </div>
  );

  return (
    <div className="stack">
      {section("Agent", "agent", [
        ["Name", <strong key="n">{settings.name}</strong>],
        ["Agent", agent ? `${agent.name} (${agent.app_id} v${agent.app_version})` : "—"],
        ["Connection", connection?.name ?? "—"],
        [
          "Caller numbers",
          settings.caller_numbers === null ? (
            `All ${numbers.length} numbers on the connection`
          ) : (
            <span className="mono" key="c">
              {numbers.join(", ")}
            </span>
          ),
        ],
        ...(settings.app_overrides.initial_bot_message
          ? ([["Opening message", `"${settings.app_overrides.initial_bot_message}"`]] as [string, string][])
          : []),
      ])}
      {section("Pacing & retries", "schedule", [
        ["Pace", `${settings.attempts_per_second} attempts per second`],
        ["Attempts", `Up to ${rp.max_attempts} per contact${rp.backoff > 1 ? `, each retry waits ${rp.backoff}× longer` : ""}`],
        ["Short call", `Under ${rp.short_call_threshold_s} seconds`],
        [
          "Retry rules",
          <div className="chip-list" key="r">
            {RETRY_OUTCOMES.map((o) => (
              <span key={o} className="chip">
                {OUTCOME_LABEL[o]}: {rp.rules[o].enabled ? `after ${delayText(rp.rules[o].delay_s)}` : "no retry"}
              </span>
            ))}
          </div>,
        ],
      ])}
      {section("Schedule", "schedule", [
        ["Starts", settings.start_at ? formatDateTime(settings.start_at) : "As soon as you start it"],
        ["Ends", settings.end_at ? formatDateTime(settings.end_at) : "When every contact is done"],
        [
          "Calling window",
          `${describeDays(cw.days)}, ${cw.start} to ${cw.end} ${zoneAbbreviation(cw.timezone)} (${cw.timezone.replace(/_/g, " ")})`,
        ],
      ])}
    </div>
  );
}
