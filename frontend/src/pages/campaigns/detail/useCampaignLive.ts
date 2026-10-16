import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { EventStreamContentType, fetchEventSource } from "@microsoft/fetch-event-source";
import { API_BASE, getToken } from "../../../api/client";
import { keys, useCampaignStats } from "../../../api/queries";
import type { CampaignStats, ContactPage, LiveEvent } from "../../../api/types";

export type LiveMode = "connecting" | "live" | "polling";

class FatalStreamError extends Error {}

const POLL_MS = 3000;
const RETRY_MS = 5000;
// The server sends a stats snapshot every 5 s, so 10 s of silence means the stream is stuck.
const STALL_MS = 10_000;
const FLASH_MS = 1600;

/**
 * Live campaign state. Stats arrive over server-sent events (a snapshot on connect and every
 * 5 s); contact changes carry the full row state and are patched into cached table pages. If the stream
 * can't be opened or goes quiet, stats are polled every 3 s while it reconnects.
 */
export function useCampaignLive(campaignId: string) {
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<LiveMode>("connecting");
  const [flash, setFlash] = useState<ReadonlyMap<string, number>>(new Map());

  const stats = useCampaignStats(campaignId, { pollMs: mode === "live" ? false : POLL_MS });

  useEffect(() => {
    let ctrl: AbortController | null = null;
    let lastEventAt = Date.now();
    setMode("connecting");

    function applyUpdates(events: LiveEvent[]) {
      const touched = new Map<string, LiveEvent & { type: "contact.updated" }>();
      let campaignChanged = false;
      for (const ev of events) {
        if (ev.type === "contact.updated") touched.set(ev.contact_id, ev);
        else if (ev.type === "campaign.updated") campaignChanged = true;
      }

      if (touched.size > 0) {
        queryClient.setQueriesData<ContactPage>({ queryKey: keys.contacts(campaignId) }, (page) =>
          page
            ? {
                ...page,
                items: page.items.map((c) => {
                  const ev = touched.get(c.id);
                  if (!ev) return c;
                  return {
                    ...c,
                    status: ev.status,
                    attempts_made: ev.attempts_made,
                    last_outcome: ev.last_outcome !== undefined ? ev.last_outcome : c.last_outcome,
                    next_attempt_at: ev.next_attempt_at !== undefined ? ev.next_attempt_at : c.next_attempt_at,
                    updated_at: ev.updated_at ?? c.updated_at,
                  };
                }),
              }
            : page,
        );
        for (const id of touched.keys()) {
          queryClient.invalidateQueries({ queryKey: keys.contact(id), exact: true });
        }
        const until = Date.now() + FLASH_MS;
        setFlash((prev) => {
          const next = new Map(prev);
          for (const id of touched.keys()) next.set(id, until);
          return next;
        });
      }

      if (campaignChanged) {
        queryClient.invalidateQueries({ queryKey: keys.campaign(campaignId), exact: true });
        queryClient.invalidateQueries({ queryKey: keys.stats(campaignId), exact: true });
      }
    }

    function connect() {
      ctrl?.abort();
      const current = new AbortController();
      ctrl = current;
      lastEventAt = Date.now();

      fetchEventSource(`${API_BASE}/campaigns/${campaignId}/events`, {
        signal: current.signal,
        headers: { Authorization: `Bearer ${getToken() ?? ""}` },
        openWhenHidden: true,
        async onopen(res) {
          const type = res.headers.get("content-type") ?? "";
          // "live" is set when the first event arrives, not here: an open but silent
          // stream shouldn't stop the polling fallback.
          if (res.ok && type.startsWith(EventStreamContentType)) return;
          // 4xx won't get better by retrying (bad token, campaign gone).
          if (res.status >= 400 && res.status < 500 && res.status !== 429) {
            throw new FatalStreamError(`Live updates unavailable (${res.status})`);
          }
          throw new Error(`Live updates failed (${res.status})`);
        },
        onmessage(msg) {
          lastEventAt = Date.now();
          setMode("live");
          if (!msg.data) return;
          if (msg.event === "stats") {
            queryClient.setQueryData<CampaignStats>(keys.stats(campaignId), JSON.parse(msg.data) as CampaignStats);
          } else if (msg.event === "updates") {
            applyUpdates(JSON.parse(msg.data) as LiveEvent[]);
          }
        },
        onclose() {
          // The server ended the stream; treat it as an error so it reconnects.
          throw new Error("Live updates closed");
        },
        onerror(err) {
          setMode("polling");
          if (err instanceof FatalStreamError) throw err;
          return RETRY_MS;
        },
      }).catch(() => {
        if (!current.signal.aborted) setMode("polling");
      });
    }

    connect();
    // Watchdog: a stream can stay open while nothing comes through (a proxy holding it, a
    // stuck connection). Fall back to polling and open a fresh stream.
    const watchdog = setInterval(() => {
      if (Date.now() - lastEventAt > STALL_MS) {
        setMode("polling");
        connect();
      }
    }, 2000);

    return () => {
      clearInterval(watchdog);
      ctrl?.abort();
    };
  }, [campaignId, queryClient]);

  // Drop expired row highlights.
  useEffect(() => {
    if (flash.size === 0) return;
    const timer = setTimeout(() => {
      const now = Date.now();
      setFlash((prev) => new Map([...prev].filter(([, until]) => until > now)));
    }, 500);
    return () => clearTimeout(timer);
  }, [flash]);

  return { stats, mode, flash };
}
