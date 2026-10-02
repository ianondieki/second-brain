// The side states' sheets' own values (REQ-ENG-10 part), apart from model.ts so that only the lazily loaded sheet
// (SideSheet.tsx) carries them, not the tracker's first load (docs/spec/07 item 5: the tracker sits near the JS budget).

/** The longest question or answer, and the longest reason (state_machine.QUESTION_MAX_CHARS / REASON_MAX_CHARS). */
export const QUESTION_MAX_CHARS = 2000;
export const REASON_MAX_CHARS = 500;
/** A hold's resume date: at most this many calendar days ahead (policy.yaml on_hold.max_days). */
export const HOLD_MAX_DAYS = 60;

/** A calendar date `days` after another ("2026-10-02" + 60), for the hold's latest resume date. */
export function addDays(day: string, days: number): string {
  const [y, m, d] = day.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d + days)).toISOString().slice(0, 10);
}

/** A calendar date with its weekday, as a person says it ("Monday, 12 October 2026"; Swahili "Jumatatu, 12 Oktoba 2026"). */
export function longDate(day: string, locale = "en"): string {
  const [y, m, d] = day.split("-").map(Number);
  return new Intl.DateTimeFormat(`${locale}-KE`, {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(Date.UTC(y, m - 1, d)));
}
