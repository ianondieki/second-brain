import { api, type ApiClient } from "@/lib/api/client";

import { settleEvent, type EventBody, type EventOut, type EventOutcome } from "./event-draft";

// The event screens' browser calls (REQ-DEV-02; same-origin /api, the typed client adds the CSRF header): an
// organisation's editors post and cancel its events; staff post platform events and cancel any. Each settles into its
// value or a refusal the screen words.

/** Who acts: an organisation (its own events) or the staff console. */
export type EventPoster = { kind: "org"; orgId: string } | { kind: "staff" };

export interface EventCalls {
  post: (poster: EventPoster, body: EventBody) => Promise<EventOutcome<EventOut>>;
  cancel: (poster: EventPoster, eventId: string) => Promise<EventOutcome<EventOut>>;
}

export function eventCalls(client: ApiClient = api): EventCalls {
  return {
    post: (poster, body) =>
      settleEvent(
        poster.kind === "org"
          ? client.POST("/api/orgs/{org_id}/events", { params: { path: { org_id: poster.orgId } }, body })
          : client.POST("/api/admin/events", { body }),
      ),
    cancel: (poster, eventId) =>
      settleEvent(
        poster.kind === "org"
          ? client.POST("/api/orgs/{org_id}/events/{event_id}/cancel", { params: { path: { org_id: poster.orgId, event_id: eventId } } })
          : client.POST("/api/admin/events/{event_id}/cancel", { params: { path: { event_id: eventId } } }),
      ),
  };
}
