import { redirect } from "next/navigation";
import { cache } from "react";

import type { EventOut } from "@/components/events/event-draft";
import { forwardHeaders, serverApi } from "@/lib/api/server";

import { isUuid } from "../membership";
import { refusalOf, type Refusal } from "../refusals";

// Server-side reads of the organisation's events (REQ-DEV-02; /api/orgs/{org_id}/events), any member, bounded like the
// other organisation reads so a hung API ends in the route's error page. Posting and cancelling are browser calls.

const TIMEOUT_MS = 5000;

async function options() {
  return { headers: await forwardHeaders(), signal: AbortSignal.timeout(TIMEOUT_MS), cache: "no-store" as const };
}

export type EventsRead<T> = { kind: "ok"; value: T } | { kind: "refused"; refusal: Refusal };

function refused(status: number, error: unknown, path: string): { kind: "refused"; refusal: Refusal } {
  const refusal = refusalOf(status, error);
  if (refusal === "mfa_required") return { kind: "refused", refusal };
  if (status === 401) redirect("/login");
  if (refusal === "generic") throw new Error(`${path} answered ${status}`);
  return { kind: "refused", refusal };
}

/** The organisation's events, newest first, every status. */
export const getOrgEvents = cache(async function getOrgEvents(orgId: string): Promise<EventsRead<EventOut[]>> {
  const { data, error, response } = await serverApi().GET("/api/orgs/{org_id}/events", {
    params: { path: { org_id: orgId }, query: { limit: 100 } },
    ...(await options()),
  });
  if (data) return { kind: "ok", value: data.items };
  return refused(response.status, error, "GET /api/orgs/{org_id}/events");
});

/** One of the organisation's events, or null when it has none with that id (another organisation's answers 404). */
export const getOrgEvent = cache(async function getOrgEvent(orgId: string, eventId: string): Promise<EventsRead<EventOut> | null> {
  if (!isUuid(eventId)) return null;
  const { data, error, response } = await serverApi().GET("/api/orgs/{org_id}/events/{event_id}", {
    params: { path: { org_id: orgId, event_id: eventId } },
    ...(await options()),
  });
  if (data) return { kind: "ok", value: data };
  if (response.status === 404) return null;
  return refused(response.status, error, "GET /api/orgs/{org_id}/events/{event_id}");
});
