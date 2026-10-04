import { NAIROBI } from "@/lib/format";

// The Notifications page's day groups (P19-C): the API stores UTC and the page reads in Nairobi (docs/spec/07 item 7),
// so 22:30 UTC on 1 Oct is a notification of 2 Oct. Pure, so the grouping is tested without a page.

/** "2026-10-02": a moment's calendar day in Nairobi. */
export function nairobiDay(at: Date | string): string {
  // en-CA writes the ISO order (YYYY-MM-DD).
  return new Intl.DateTimeFormat("en-CA", { timeZone: NAIROBI, year: "numeric", month: "2-digit", day: "2-digit" }).format(
    typeof at === "string" ? new Date(at) : at,
  );
}

/** The day before a "YYYY-MM-DD" day (Nairobi has no daylight saving: a day is always 24 hours). */
function dayBefore(day: string): string {
  const [y, m, d] = day.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d - 1)).toISOString().slice(0, 10);
}

export type DayName = "today" | "yesterday" | "date";

export interface DayGroup<T> {
  /** The Nairobi day, "YYYY-MM-DD" (a stable key and the heading's id). */
  day: string;
  /** Today and Yesterday by name; any other day by its date. */
  name: DayName;
  /** The first item's moment, for writing the date ("30 Sep 2026"). */
  at: string;
  items: T[];
}

/**
 * Items (newest first, as the API answers) in groups of one Nairobi day each, in the same order: Today, Yesterday,
 * then the earlier dates. `now` decides which day is today.
 */
export function groupByDay<T extends { created_at: string }>(items: readonly T[], now: Date): DayGroup<T>[] {
  const today = nairobiDay(now);
  const yesterday = dayBefore(today);
  const groups: DayGroup<T>[] = [];
  for (const item of items) {
    const day = nairobiDay(item.created_at);
    const last = groups.at(-1);
    if (last && last.day === day) {
      last.items.push(item);
      continue;
    }
    const name: DayName = day === today ? "today" : day === yesterday ? "yesterday" : "date";
    groups.push({ day, name, at: item.created_at, items: [item] });
  }
  return groups;
}
