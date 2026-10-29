import { apiErrorCode } from "@/lib/api/error-code";

// "Remind me" on an event's page (REQ-DEV-02; D-61; P22 card B default (4)): which sentence says what will come, and
// what a refused call means. Its own module, so the page's one client component loads nothing else.

/** The day-before email's gate as the API answers it (WeekOut.reminders_email, ReminderOut.email). */
export type EmailState = "on" | "no_consent" | "unverified";

/**
 * What a reminder brings, as the sentence under "Remind me" names it (`week.reminder.*`): the day-before email and
 * the morning notice when email reminders are on; the morning notice alone otherwise, with the reason and its way to
 * fix it (the reminders consent in Settings, or the address to verify). Before the reminder is set it says what would
 * come; after, what will.
 */
export type ReminderLine = "both" | "noConsent" | "unverified";

export function reminderLine(email: EmailState): ReminderLine {
  return email === "on" ? "both" : email === "no_consent" ? "noConsent" : "unverified";
}

/** A refused reminder call: the event is gone or over (404), the session ended (401), or anything else. */
export type ReminderRefusal = "gone" | "signedOut" | "generic";

export function reminderRefusal(status: number, error: unknown): ReminderRefusal {
  if (status === 401) return "signedOut";
  if (status === 404 || apiErrorCode(error) === "not_found") return "gone";
  return "generic";
}
