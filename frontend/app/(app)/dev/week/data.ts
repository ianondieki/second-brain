import { notFound, redirect } from "next/navigation";
import { cache } from "react";

import { isUuid } from "@/app/(app)/org/membership";
import { forwardHeaders, serverApi } from "@/lib/api/server";

import type { EventPage, TrendDetail, Week, WeekEvents } from "./week";

// Server-side reads of This week (REQ-DEV-02; bridge/events/router.py), signed in, developers only (the API answers
// 404 to anyone else). Each is bounded, so a hung API ends in the route's error page (or, on Home, in a Home without
// the strip) instead of a page that never renders.
const TIMEOUT_MS = 5000;
const HOME = "/dev";

async function options() {
  return { headers: await forwardHeaders(), signal: AbortSignal.timeout(TIMEOUT_MS), cache: "no-store" as const };
}

/**
 * Home's "This week" strip: up to three events, the trend of the day and the email gate, or null when the strip is
 * left out (a refusal, no answer in time, the network): Home stands without it and never shows the error page for it.
 * Only a lost session (401) leaves Home, to sign in again. Read once per request (the week's page and the event page
 * take the trend and the email gate from it).
 */
export const weekStrip = cache(async function weekStrip(): Promise<Week | null> {
  let answer;
  try {
    answer = await serverApi().GET("/api/me/week", await options());
  } catch {
    return null;
  }
  if (answer.data) return answer.data;
  if (answer.response.status === 401) redirect("/login");
  return null;
});

/** /dev/week: every event of this week and next. A 404 (the page is not for this account) goes back to Home. */
export async function weekEvents(): Promise<WeekEvents> {
  const { data, response } = await serverApi().GET("/api/me/week/events", await options());
  if (data) return data;
  if (response.status === 401) redirect("/login");
  if (response.status === 404) redirect(HOME);
  throw new Error(`GET /api/me/week/events answered ${response.status}`);
}

/**
 * The trend of the day for /dev/week (the strip's read, which also carries it); null when there is none or it could
 * not be read: the page stands with its events.
 */
export async function trendOfTheDay(): Promise<Week["trend"]> {
  return (await weekStrip())?.trend ?? null;
}

/**
 * One published event's page. Not published, cancelled, over or unknown: the not-found page (the API answers 404 for
 * each, and never says which).
 */
export async function eventPage(id: string): Promise<EventPage> {
  if (!isUuid(id)) notFound();
  const { data, response } = await serverApi().GET("/api/events/{event_id}", {
    params: { path: { event_id: id } },
    ...(await options()),
  });
  if (data) return data;
  if (response.status === 401) redirect("/login");
  if (response.status === 404) notFound();
  throw new Error(`GET /api/events/{event_id} answered ${response.status}`);
}

/** The email gate's answer for the event page's sentence before "Remind me" is pressed (null: not read). */
export async function emailState(): Promise<Week["reminders_email"] | null> {
  return (await weekStrip())?.reminders_email ?? null;
}

/** One published trend card with its sources; anything else is the not-found page. */
export async function trendPage(id: string): Promise<TrendDetail> {
  if (!isUuid(id)) notFound();
  const { data, response } = await serverApi().GET("/api/me/trends/{card_id}", {
    params: { path: { card_id: id } },
    ...(await options()),
  });
  if (data) return data;
  if (response.status === 401) redirect("/login");
  if (response.status === 404) notFound();
  throw new Error(`GET /api/me/trends/{card_id} answered ${response.status}`);
}
