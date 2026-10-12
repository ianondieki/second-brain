import type { components } from "@/lib/api/schema";
import { NAIROBI } from "@/lib/format";

// The Calendar tab's arithmetic (P27 track A; REQ-ENG-13): which month is shown, its weeks Monday first, and which
// deadlines fall on which day. Days are Nairobi dates ("2026-10-16"), the API's `due_on`, never a browser's zone.

export type Deadline = components["schemas"]["DeadlineOut"];
export type DeadlineKind = components["schemas"]["DeadlineKind"];

const DAY_MS = 86_400_000;
const MONTH = /^(\d{4})-(0[1-9]|1[0-2])$/;

/** The Nairobi date of an instant ("2026-10-12" for 2026-10-12T21:30Z, already the 13th in Nairobi: "2026-10-13"). */
export function nairobiDay(iso: string): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: NAIROBI, year: "numeric", month: "2-digit", day: "2-digit" }).format(
    new Date(iso),
  );
}

/** A day `n` days after `day` (negative: before). */
export function addDays(day: string, n: number): string {
  return new Date(Date.parse(`${day}T00:00:00Z`) + n * DAY_MS).toISOString().slice(0, 10);
}

/** "2026-10" from `?month=`, when it is a real month; else the month of `today`. */
export function pickMonth(requested: string | string[] | undefined, today: string): string {
  const value = Array.isArray(requested) ? requested[0] : requested;
  return value && MONTH.test(value) ? value : today.slice(0, 7);
}

/** The month before or after ("2026-10" → "2026-09" / "2026-11"). */
export function shiftMonth(month: string, by: -1 | 1): string {
  const [year, mon] = month.split("-").map(Number);
  const date = new Date(Date.UTC(year, mon - 1 + by, 1));
  return date.toISOString().slice(0, 7);
}

export interface MonthDay {
  /** "2026-10-16" */
  day: string;
  /** Falls in the month shown (the first and last weeks carry the neighbours' days). */
  inMonth: boolean;
}

/** The month's weeks, Monday first: four to six rows of seven days. */
export function monthWeeks(month: string): MonthDay[][] {
  const first = `${month}-01`;
  const start = addDays(first, -((new Date(`${first}T00:00:00Z`).getUTCDay() + 6) % 7));
  const last = addDays(`${shiftMonth(month, 1)}-01`, -1);
  const weeks: MonthDay[][] = [];
  for (let day = start; day <= last; ) {
    const week: MonthDay[] = [];
    for (let d = 0; d < 7; d += 1, day = addDays(day, 1)) week.push({ day, inMonth: day.slice(0, 7) === month });
    weeks.push(week);
  }
  return weeks;
}

/** The first and last day the month's grid shows (the API's `from` and `to`). */
export function gridSpan(month: string): { from: string; to: string } {
  const weeks = monthWeeks(month);
  return { from: weeks[0][0].day, to: weeks.at(-1)![6].day };
}

/** The deadlines by their Nairobi day, in the API's order (by instant). */
export function byDay(items: readonly Deadline[]): Map<string, Deadline[]> {
  const days = new Map<string, Deadline[]>();
  for (const item of items) days.set(item.due_on, [...(days.get(item.due_on) ?? []), item]);
  return days;
}

/** The kind and the item's id from its key ("stage:<uuid>"), for its `.ics` route. */
export function keyParts(item: Pick<Deadline, "key" | "kind">): { kind: DeadlineKind; id: string } {
  const at = item.key.indexOf(":");
  return { kind: item.kind, id: at >= 0 ? item.key.slice(at + 1) : item.key };
}

/** The list under the grid: what is overdue, then what falls due from today through the next 30 days. */
export function upcoming(items: readonly Deadline[], today: string): { overdue: Deadline[]; next: Deadline[] } {
  const end = addDays(today, 30);
  return {
    overdue: items.filter((item) => item.overdue),
    next: items.filter((item) => !item.overdue && item.due_on >= today && item.due_on <= end),
  };
}

/** A Google Calendar template link for a deadline: a 15-minute entry at its instant, as the `.ics` file has (D-61). */
export function googleCalendarHref(item: Pick<Deadline, "due_at">, text: string, details: string): string {
  const stamp = (time: number) => new Date(time).toISOString().replace(/[-:]/g, "").replace(/\.\d{3}/, "");
  const start = Date.parse(item.due_at);
  const params = new URLSearchParams({
    action: "TEMPLATE",
    text,
    dates: `${stamp(start)}/${stamp(start + 15 * 60_000)}`,
    details,
    ctz: NAIROBI,
  });
  return `https://calendar.google.com/calendar/render?${params}`;
}
