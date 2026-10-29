import type { EventOut, EventStatus } from "@/components/events/event-draft";
import { serverApi } from "@/lib/api/server";

import { combine, readOptions as options, settle, type Loaded } from "../load";
import { VIEW_STATUSES, type EventsView } from "./events";

// Server-side reads of the staff events API (REQ-DEV-02; /api/admin/events) through the console's shared loader
// (../load.ts): staff admins and moderators with a fresh second factor.

async function ofStatus(status: EventStatus): Promise<Loaded<EventOut[]>> {
  const answer = await serverApi().GET("/api/admin/events", { params: { query: { status, limit: 200 } }, ...(await options()) });
  return settle("GET /api/admin/events", { ...answer, data: answer.data?.items });
}

/** The events of one view (one status, or rejected and cancelled together), at most 200 of each status. */
export async function getAdminEvents(view: EventsView): Promise<Loaded<EventOut[]>> {
  const loaded = combine<EventOut[][]>(...(await Promise.all(VIEW_STATUSES[view].map(ofStatus))));
  return loaded.kind === "ok" ? { kind: "ok", data: loaded.data.flat() } : loaded;
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
