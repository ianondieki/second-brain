import type { EventOut, EventStatus } from "@/components/events/event-draft";
import { serverApi } from "@/lib/api/server";

import { readOptions as options, settle, type Loaded } from "../load";

// Server-side reads of the staff events API (REQ-DEV-02; /api/admin/events) through the console's shared loader
// (../load.ts): staff admins and moderators with a fresh second factor.

/** The events of one status, newest first (at most 200). */
export async function getAdminEvents(status: EventStatus): Promise<Loaded<EventOut[]>> {
  const answer = await serverApi().GET("/api/admin/events", { params: { query: { status, limit: 200 } }, ...(await options()) });
  return settle("GET /api/admin/events", { ...answer, data: answer.data?.items });
}

/** One event; null when there is no such event (404). */
export async function getAdminEvent(eventId: string): Promise<Loaded<EventOut | null>> {
  const answer = await serverApi().GET("/api/admin/events/{event_id}", {
    params: { path: { event_id: eventId } },
    ...(await options()),
  });
  if (answer.response.status === 404) return { kind: "ok", data: null };
  return settle("GET /api/admin/events/{event_id}", answer);
}
