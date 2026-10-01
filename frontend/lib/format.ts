// Dates as the web app writes them (REQ-UX-07; docs/spec/07 item 7: store UTC, display Africa/Nairobi). One format
// everywhere: "30 Sep 2026" for a day, "30 Sep 2026, 14:06" for a moment (docs/spec/06 6.9's "23 Sep 2026, 14:05 EAT";
// the message around it adds "EAT" or "Nairobi time"). Every screen goes through these functions, so a day never
// reads "Sept" on one page and "Sep" on the next.

export const NAIROBI = "Africa/Nairobi";

const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/;

/**
 * The day, the three-letter month and the year in the page's language. en-KE on its own writes "Sept", so the month
 * comes from the short month names that use three letters (en-US for English); the order and spacing stay en-KE's.
 */
function dayMonthYear(at: Date, locale: string, timeZone: string, withTime: false | "minutes" | "seconds" = false): string {
  const month = new Intl.DateTimeFormat(locale === "en" ? "en-US" : `${locale}-KE`, { month: "short", timeZone }).format(at);
  const time: Intl.DateTimeFormatOptions = withTime
    ? { hour: "2-digit", minute: "2-digit", ...(withTime === "seconds" ? { second: "2-digit" } : {}), hourCycle: "h23" }
    : {};
  return new Intl.DateTimeFormat(`${locale}-KE`, { day: "numeric", month: "short", year: "numeric", timeZone, ...time })
    .formatToParts(at)
    .map((part) => (part.type === "month" ? month : part.value))
    .join("");
}

/** A moment's time of day in Nairobi, on the 24-hour clock ("14:06"). */
export function formatTime(locale: string, iso: string): string {
  return new Intl.DateTimeFormat(`${locale}-KE`, {
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
    timeZone: NAIROBI,
  }).format(new Date(iso));
}

/** A moment as its date and time in Nairobi, apart ("30 Sep 2026", "14:06"), for messages that place them. */
export function nairobiParts(locale: string, iso: string): { date: string; time: string } {
  return { date: dayMonthYear(new Date(iso), locale, NAIROBI), time: formatTime(locale, iso) };
}

/** A moment's day in Nairobi ("30 Sep 2026"); the API stores UTC, so 22:30 UTC is already the next day. */
export function formatDay(locale: string, iso: string): string {
  return dayMonthYear(new Date(iso), locale, NAIROBI);
}

/** A moment in Nairobi, day and time ("30 Sep 2026, 14:06"; the language's own separator between them). */
export function formatMoment(locale: string, iso: string): string {
  return dayMonthYear(new Date(iso), locale, NAIROBI, "minutes");
}

/**
 * A moment to the second, in the one format ("30 Sep 2026, 10:49:20"), in Nairobi or another zone ("UTC"): the
 * certificate page, where a timestamp authority's time is read to the second. The message around it names the zone.
 */
export function formatMomentSeconds(locale: string, iso: string, timeZone: string = NAIROBI): string {
  return dayMonthYear(new Date(iso), locale, timeZone, "seconds");
}

/**
 * A calendar date from the API ("2026-10-02", no time or zone) as "2 Oct 2026", never shifted a day. Anything that is
 * not such a date is returned as it is.
 */
/** A calendar day as "3 Oct" (no year): a tile's figure. */
export function formatShortDate(locale: string, day: string): string {
  if (!DATE_ONLY.test(day)) return day;
  const [y, m, d] = day.split("-").map(Number);
  return new Intl.DateTimeFormat(locale, { day: "numeric", month: "short", timeZone: "UTC" }).format(new Date(Date.UTC(y, m - 1, d)));
}

export function formatCalendarDate(locale: string, day: string): string {
  if (!DATE_ONLY.test(day)) return day;
  const [y, m, d] = day.split("-").map(Number);
  return dayMonthYear(new Date(Date.UTC(y, m - 1, d)), locale, "UTC");
}
