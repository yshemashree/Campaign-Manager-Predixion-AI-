import type { Segment } from "../lib/contactStatus";

/** Stacked bar; segments are separated by a 2px gap so neighbours stay distinct. */
export function ProgressBar({ segments, total, thin }: { segments: Segment[]; total: number; thin?: boolean }) {
  const visible = segments.filter((s) => s.value > 0 && s.key !== "pending");
  return (
    <div
      className={`progress ${thin ? "progress--thin" : ""}`}
      role="img"
      aria-label={visible.map((s) => `${s.label} ${s.value}`).join(", ") || "No contacts"}
    >
      {total > 0 &&
        visible.map((s) => (
          <div
            key={s.key}
            className="progress__seg"
            title={`${s.label}: ${s.value.toLocaleString()}`}
            style={{ width: `${(s.value / total) * 100}%`, background: s.colour }}
          />
        ))}
    </div>
  );
}
