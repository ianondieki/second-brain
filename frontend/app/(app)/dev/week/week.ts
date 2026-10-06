import { safeHttpsUrl } from "@/components/problem/problem";
import type { components } from "@/lib/api/schema";
import { NAIROBI } from "@/lib/format";

// This week's pure parts (REQ-DEV-02; D-60, D-61; docs/platform/tasks/P22.md section B): the addresses, an event's
// day and time in Nairobi, the week's events grouped by day, and which sentence says what a reminder will bring. The
// API decides who sees what; this only words it.

type Schemas = components["schemas"];
export type Week = Schemas["WeekOut"];
export type WeekEvent = Schemas["WeekEventOut"];
export type WeekEvents = Schemas["WeekEventsOut"];
export type EventPage = Schemas["EventPageOut"];
export type TrendCard = Schemas["TrendCardOut"];
export type TrendDetail = Schemas["TrendCardDetailOut"];
export type { EmailState } from "../events/reminder";

export const WEEK_PATH = "/dev/week";
export const NOTIFICATION_SETTINGS_PATH = "/settings/notifications";

export function eventHref(id: string): string {
  return `/dev/events/${encodeURIComponent(id)}`;
}

export function trendHref(id: string): string {
  return `/dev/trends/${encodeURIComponent(id)}`;
}

/** The Nairobi calendar day of a moment ("2026-11-22"), the key the week's page groups by. */
export function nairobiDate(iso: string): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: NAIROBI }).format(new Date(iso));
}

/**
 * An event's day as a row writes it, in Nairobi: "Sun 22 Nov" (the short weekday, the day, the three-letter month as
 * lib/format.ts writes it; the language's own order, without the comma after the weekday).
 */
export function eventDay(locale: string, iso: string): string {
  const at = new Date(iso);
  const month = new Intl.DateTimeFormat(locale === "en" ? "en-US" : `${locale}-KE`, { month: "short", timeZone: NAIROBI }).format(at);
  return new Intl.DateTimeFormat(`${locale}-KE`, { weekday: "short", day: "numeric", month: "short", timeZone: NAIROBI })
    .formatToParts(at)
    .map((part) => (part.type === "month" ? month : part.type === "literal" ? part.value.replace(",", "") : part.value))
    .join("");
}

/** A day heading on the week's page: "Sunday, 22 November" in Nairobi. */
export function longDay(locale: string, iso: string): string {
  return new Intl.DateTimeFormat(`${locale}-KE`, { weekday: "long", day: "numeric", month: "long", timeZone: NAIROBI }).format(
    new Date(iso),
  );
}

/** The week's events by Nairobi day, in the API's order (soonest first), each day once. */
export function byDay<T extends Pick<WeekEvent, "starts_at">>(events: readonly T[]): { day: string; first: string; events: T[] }[] {
  const groups: { day: string; first: string; events: T[] }[] = [];
  for (const event of events) {
    const day = nairobiDate(event.starts_at);
    const group = groups.find((g) => g.day === day);
    if (group) group.events.push(event);
    else groups.push({ day, first: event.starts_at, events: [event] });
  }
  return groups;
}

/** Whether an event ends on a later Nairobi day than it starts (then the page names both days). */
export function spansDays(event: Pick<WeekEvent, "starts_at" | "ends_at">): boolean {
  return nairobiDate(event.starts_at) !== nairobiDate(event.ends_at);
}

/** An address the page links to: plain https only (the API checks the same when the event is posted). */
export function safeHttps(url: string | null | undefined): string | null {
  return url ? safeHttpsUrl(url) : null;
}

/** The `.ics` link: the API's own path (same origin), never built here; anything else is not linked. */
export function calendarHref(path: string): string | null {
  return /^\/api\/events\/[0-9a-f-]{36}\/calendar\.ics$/.test(path) ? path : null;
}
