import { formatCalendarDate } from "@/lib/format";

// Helpers of the tracker's forms and sheets (CommandForm, SideSheet: both load when one opens) and of the server's
// screens, kept out of ./model so the first load of a tracker carries none of them (docs/spec/07 item 5, the JS
// budget). ./model re-exports them.

/** Whole or decimal shillings typed in a form, as minor units; null when it is not a positive amount. */
export function toMinor(text: string): number | null {
  const clean = text.replace(/[,\s]/g, "");
  if (!/^\d+(\.\d{1,2})?$/.test(clean)) return null;
  const minor = Math.round(Number(clean) * 100);
  return minor > 0 ? minor : null;
}

/** A calendar date from the API ("2026-10-02") as written in Kenya ("2 Oct 2026"); dates carry no time zone. */
export function formatDate(day: string, locale = "en"): string {
  return formatCalendarDate(locale, day);
}

/** Today's date in Nairobi ("2026-09-29"), for date inputs. */
export function nairobiToday(now: Date = new Date()): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Africa/Nairobi" }).format(now);
}
