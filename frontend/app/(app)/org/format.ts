// Dates on the organisation screens: stored in UTC by the API, shown in Nairobi time (docs/spec/07 item 7).

/** A day as written in Kenya for the page's language ("29 Sept 2026"). */
export function formatDay(locale: string, iso: string): string {
  return new Intl.DateTimeFormat(`${locale}-KE`, { dateStyle: "medium", timeZone: "Africa/Nairobi" }).format(
    new Date(iso),
  );
}

/** A date and time in Nairobi ("29 September 2026 at 14:06"). */
export function formatMoment(locale: string, iso: string): string {
  return new Intl.DateTimeFormat(`${locale}-KE`, {
    dateStyle: "long",
    timeStyle: "short",
    timeZone: "Africa/Nairobi",
  }).format(new Date(iso));
}
