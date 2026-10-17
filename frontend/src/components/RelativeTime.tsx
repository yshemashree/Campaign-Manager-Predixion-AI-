import { useEffect, useState } from "react";
import { formatDateTime, formatRelative } from "../lib/format";

// One shared ticker so every relative time on screen moves together.
const listeners = new Set<() => void>();
let timer: ReturnType<typeof setInterval> | null = null;

function useMinuteTick(): number {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const tick = () => setNow(Date.now());
    listeners.add(tick);
    timer ??= setInterval(() => listeners.forEach((l) => l()), 15_000);
    return () => {
      listeners.delete(tick);
      if (listeners.size === 0 && timer) {
        clearInterval(timer);
        timer = null;
      }
    };
  }, []);
  return now;
}

/** "in 12 min" with the exact time in a tooltip. */
export function RelativeTime({ iso, dueLabel }: { iso: string | null | undefined; dueLabel?: string }) {
  const now = useMinuteTick();
  if (!iso) return <span className="faint">—</span>;
  const past = new Date(iso).getTime() <= now;
  return (
    <time dateTime={iso} title={formatDateTime(iso)} className="reltime">
      {past && dueLabel ? dueLabel : formatRelative(iso, now)}
    </time>
  );
}
