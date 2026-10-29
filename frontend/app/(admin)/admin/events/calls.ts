import { api, type ApiClient } from "@/lib/api/client";

import type { EventOut } from "@/components/events/event-draft";

import { decisionRefusalOf, type Decision, type DecisionRefusal } from "./events";

// The staff decision on an event (REQ-DEV-02; POST /api/admin/events/{id}/decision), from the browser: the decision and
// the version the reviewer read (`seen`, the event's updated_at exactly as the page's GET returned it).

export type DecisionOutcome = { ok: true; value: EventOut } | { ok: false; refusal: DecisionRefusal };

export interface AdminEventCalls {
  decide: (eventId: string, decision: Decision, seen: string) => Promise<DecisionOutcome>;
}

export function adminEventCalls(client: ApiClient = api): AdminEventCalls {
  return {
    async decide(eventId, decision, seen) {
      try {
        const { data, error, response } = await client.POST("/api/admin/events/{event_id}/decision", {
          params: { path: { event_id: eventId } },
          body: { decision, seen },
        });
        if (response.ok && data) return { ok: true, value: data };
        return { ok: false, refusal: decisionRefusalOf(response.status, error) };
      } catch {
        return { ok: false, refusal: { kind: "refusal", code: "generic" } };
      }
    },
  };
}
