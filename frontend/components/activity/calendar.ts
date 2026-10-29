import type { components } from "@/lib/api/schema";

// The activity calendar's data (D-67, P25): GET /api/me/activity?weeks=26 (the generated schema's ActivityCalendar),
// checked field by field before it is drawn, and the grid it draws: weeks as columns, Monday first, each day's count
// on a five-step scale. Pure, so it is tested without a server.

export const WEEKS = 26;
const DATE = /^\d{4}-\d{2}-\d{2}$/;
const DAY_MS = 86_400_000;

export type Activity = components["schemas"]["ActivityCalendar"];
type Kind = components["schemas"]["ActivityKindCount"]["kind"];
const KINDS: readonly Kind[] = ["version_registered", "proposal_published", "engagement_step", "message_sent", "quiz_answered", "team_message", "proposal_opened", "brief_posted"];

const count = (value: unknown): value is number => typeof value === "number" && Number.isInteger(value) && value >= 0;
const date = (value: unknown): value is string => typeof value === "string" && DATE.test(value);

/** The answer when it has the documented shape `{from, to, timezone, days, kinds, total}`, else null (no card). */
export function parseActivity(body: unknown): Activity | null {
  if (!body || typeof body !== "object") return null;
  const { from, to, timezone, days, kinds, total } = body as Record<string, unknown>;
  if (!date(from) || !date(to) || from > to || timezone !== "Africa/Nairobi" || !count(total)) return null;
  if (!Array.isArray(days) || !Array.isArray(kinds)) return null;
  const okDays = days.every((d) => d && typeof d === "object" && date((d as { date?: unknown }).date) && count((d as { count?: unknown }).count));
  const okKinds = kinds.every((k) => k && typeof k === "object" && typeof (k as { kind?: unknown }).kind === "string" && count((k as { count?: unknown }).count));
  if (!okDays || !okKinds) return null;
  // A kind this build does not know (a later API) counts in the total but is not named.
  const known = (kinds as { kind: string; count: number }[]).filter((k): k is { kind: Kind; count: number } => (KINDS as readonly string[]).includes(k.kind));
  return {
    from,
    to,
    timezone: "Africa/Nairobi",
    total,
    days: (days as Activity["days"]).map(({ date: d, count: c }) => ({ date: d, count: c })),
    kinds: known.map(({ kind, count: c }) => ({ kind, count: c })),
  };
}

const toTime = (day: string) => Date.parse(`${day}T00:00:00Z`);
const toDay = (time: number) => new Date(time).toISOString().slice(0, 10);

/** A day's step on the scale: 0 for none, then 1–4 by its share of the busiest day (so one busy day sets the top). */
export function level(value: number, max: number): 0 | 1 | 2 | 3 | 4 {
  if (value <= 0 || max <= 0) return 0;
  return Math.min(4, Math.max(1, Math.ceil((4 * value) / max))) as 1 | 2 | 3 | 4;
}

export interface Cell {
  date: string;
  count: number;
  level: 0 | 1 | 2 | 3 | 4;
  /** Before the range or after its last day (the current week's days still to come): drawn as nothing. */
  outside: boolean;
}

export interface Grid {
  /** Columns of seven days, Monday to Sunday, oldest first. */
  weeks: Cell[][];
  /** Where a month starts: the week column and the month's first day in it (for its name). */
  months: { column: number; date: string }[];
}

/**
 * The calendar's grid: week columns, Monday first, from the week of `from` to the week of `to` (27 columns for 26
 * weeks that do not start on a Monday), so every day of the range has its cell.
 */
export function buildGrid(activity: Activity): Grid {
  const counts = new Map(activity.days.map((d) => [d.date, d.count]));
  const max = Math.max(0, ...activity.days.map((d) => d.count));
  const end = toTime(activity.to);
  const first = toTime(activity.from);
  const monday = (time: number) => time - ((new Date(time).getUTCDay() + 6) % 7) * DAY_MS;
  const start = monday(first);
  const weeks = Math.round((monday(end) - start) / (7 * DAY_MS)) + 1;
  const columns: Cell[][] = [];
  const months: Grid["months"] = [];
  let lastMonth = "";
  for (let w = 0; w < weeks; w += 1) {
    const column: Cell[] = [];
    for (let d = 0; d < 7; d += 1) {
      const time = start + (w * 7 + d) * DAY_MS;
      const day = toDay(time);
      const outside = time > end || time < first;
      const value = outside ? 0 : (counts.get(day) ?? 0);
      column.push({ date: day, count: value, level: outside ? 0 : level(value, max), outside });
      // A month is named over the first week column in which its first shown day falls; a name needs three columns
      // of room, so a month that starts in the last two columns or right after another name is not named.
      const month = day.slice(0, 7);
      if (!outside && month !== lastMonth) {
        lastMonth = month;
        const previous = months.at(-1);
        if ((!previous || w - previous.column >= 3) && w <= weeks - 3) months.push({ column: w, date: day });
      }
    }
    columns.push(column);
  }
  return { weeks: columns, months };
}
