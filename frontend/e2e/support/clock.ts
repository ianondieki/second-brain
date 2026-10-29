import type { APIRequestContext } from "@playwright/test";

/**
 * The platform's day in Nairobi ("2026-10-02"), on the shared test clock (`GET /api/test-clock`, dev and test only;
 * any signed-in session may read it), else the real day. Every date a spec sends (a contact-by date, a milestone's due
 * date, a hold's resume date, a deadline) counts from it: the API checks dates against the platform clock, which the
 * walkthrough's "a day later" step and the test-clock scenarios move ahead of the real one.
 */
export async function appToday(request: APIRequestContext): Promise<string> {
  const response = await request.get("/api/test-clock");
  const now = response.ok() ? new Date(((await response.json()) as { now: string }).now) : new Date();
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Africa/Nairobi" }).format(now);
}

/** A calendar date `days` after another ("2026-10-02" + 10). */
export function plusDays(day: string, days: number): string {
  const [y, m, d] = day.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d + days)).toISOString().slice(0, 10);
}
