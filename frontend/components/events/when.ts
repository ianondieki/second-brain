import { NAIROBI } from "@/lib/format";

// An event's day and time as every events screen writes them (REQ-DEV-02): in Nairobi, whatever the reader's zone.

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
