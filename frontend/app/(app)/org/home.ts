import type { Summary } from "@/components/tracker/model";
import { awaitsMe, isFinished } from "@/components/tracker/model";

import type { InboxItem } from "./data";
import type { Match } from "./scout";

const WEEK_MS = 7 * 24 * 60 * 60 * 1000;

/**
 * How many of the dates fall in each of the last `weeks` weeks, oldest week first: the stat tiles' sparkline from the
 * list the page already reads (D-52: a series only where the data exists). A date in the future counts in this week;
 * one older than the window is left out.
 */
export function weeklySeries(dates: readonly string[], now: Date, weeks = 8): number[] {
  const counts = new Array<number>(weeks).fill(0);
  const end = now.getTime();
  for (const iso of dates) {
    const at = Date.parse(iso);
    if (Number.isNaN(at)) continue;
    const index = weeks - 1 - Math.floor(Math.max(0, end - at) / WEEK_MS);
    if (index >= 0) counts[index] += 1;
  }
  return counts;
}

export interface OrgHomeStats {
  /** Proposals on the Inbox's first page; `more` when a further page exists. */
  inbox: number;
  more: boolean;
  /** Proposals nobody at the organisation has opened yet (no engagement, or one still SUBMITTED). */
  fresh: number;
  matches: number;
  /** When the scout found its newest match. */
  newestMatch: string | null;
  engagements: number;
  active: number;
  /** Engagements waiting on the organisation. */
  waiting: Summary[];
  others: Summary[];
}

/** The figures of the organisation Home's stat tiles, from what the page already reads. */
export function orgHomeStats(
  inbox: { items: readonly InboxItem[]; next_cursor?: string | null } | null,
  matches: readonly Match[] | null,
  engagements: readonly Summary[] | null,
): OrgHomeStats {
  const items = inbox?.items ?? [];
  const all = engagements ?? [];
  const newest = (matches ?? []).map((m) => m.created_at).sort().at(-1) ?? null;
  return {
    inbox: items.length,
    more: Boolean(inbox?.next_cursor),
    fresh: items.filter((item) => !item.engagement || item.engagement.state === "SUBMITTED").length,
    matches: matches?.length ?? 0,
    newestMatch: newest,
    engagements: all.length,
    active: all.filter((item) => !isFinished(item.state)).length,
    waiting: all.filter((item) => awaitsMe(item, "org")),
    others: all.filter((item) => !awaitsMe(item, "org")),
  };
}
