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
  /** Proposals on the Inbox's first page; `more` when a further page exists; null when the Inbox could not be read. */
  inbox: number | null;
  more: boolean;
  /** Proposals nobody at the organisation has opened yet (no engagement, or one still SUBMITTED). */
  fresh: number;
  /** Null when the matches could not be read. */
  matches: number | null;
  /** When the scout found its newest match. */
  newestMatch: string | null;
  /** Null when the engagements could not be read (then `waiting` and `others` are empty, not known to be empty). */
  engagements: number | null;
  active: number;
  /** Engagements waiting on the organisation. */
  waiting: Summary[];
  others: Summary[];
}

/**
 * The figures of the organisation Home's stat tiles, from what the page already reads. A list that could not be read
 * gives a null count, never a confident zero: the tile then says it could not be read.
 */
export function orgHomeStats(
  inbox: { items: readonly InboxItem[]; next_cursor?: string | null } | null,
  matches: readonly Match[] | null,
  engagements: readonly Summary[] | null,
): OrgHomeStats {
  const items = inbox?.items ?? [];
  const all = engagements ?? [];
  const newest = (matches ?? []).map((m) => m.created_at).sort().at(-1) ?? null;
  return {
    inbox: inbox ? items.length : null,
    more: Boolean(inbox?.next_cursor),
    fresh: items.filter((item) => !item.engagement || item.engagement.state === "SUBMITTED").length,
    matches: matches ? matches.length : null,
    newestMatch: newest,
    engagements: engagements ? all.length : null,
    active: all.filter((item) => !isFinished(item.state)).length,
    waiting: all.filter((item) => awaitsMe(item, "org")),
    others: all.filter((item) => !awaitsMe(item, "org")),
  };
}
