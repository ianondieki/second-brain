import { api, type ApiClient } from "@/lib/api/client";

import { reminderRefusal, type EmailState, type ReminderRefusal } from "./reminder";

// "Remind me" from the browser (REQ-DEV-02; POST/DELETE /api/me/events/{id}/reminder; the typed client adds the CSRF
// header). Each call settles into its answer or a refusal, never a thrown error (a thrown fetch is "generic").

export type ReminderOutcome<T> = { ok: true; value: T } | { ok: false; refusal: ReminderRefusal };

export interface ReminderCalls {
  /** Remind me: what the day-before email's gate says now. */
  remind: (eventId: string) => Promise<ReminderOutcome<{ email: EmailState }>>;
  /** Don't remind me: neither the email nor the notice comes. */
  decline: (eventId: string) => Promise<ReminderOutcome<null>>;
}

export function reminderCalls(client: ApiClient = api): ReminderCalls {
  const path = (eventId: string) => ({ params: { path: { event_id: eventId } } });
  return {
    async remind(eventId) {
      try {
        const { data, error, response } = await client.POST("/api/me/events/{event_id}/reminder", path(eventId));
        if (response.ok && data) return { ok: true, value: { email: data.email } };
        return { ok: false, refusal: reminderRefusal(response.status, error) };
      } catch {
        return { ok: false, refusal: "generic" };
      }
    },
    async decline(eventId) {
      try {
        const { error, response } = await client.DELETE("/api/me/events/{event_id}/reminder", path(eventId));
        if (response.ok) return { ok: true, value: null };
        return { ok: false, refusal: reminderRefusal(response.status, error) };
      } catch {
        return { ok: false, refusal: "generic" };
      }
    },
  };
}
