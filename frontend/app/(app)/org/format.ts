import { eatParts } from "@/components/tracker/model";

// Dates on the organisation screens: stored in UTC by the API, shown in Nairobi time (docs/spec/07 item 7).

/** A moment's day in Nairobi as the tracker writes it ("29 Sep 2026"), the same on every organisation screen. */
export function formatDay(locale: string, iso: string): string {
  return eatParts(iso, locale).date;
}

/** A date and time in Nairobi ("29 September 2026 at 14:06"). */
export function formatMoment(locale: string, iso: string): string {
  return new Intl.DateTimeFormat(`${locale}-KE`, {
    dateStyle: "long",
    timeStyle: "short",
    timeZone: "Africa/Nairobi",
  }).format(new Date(iso));
}
