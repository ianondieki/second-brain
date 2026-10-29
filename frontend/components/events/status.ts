import type { ChipKind } from "@/components/tracker/model";

import type { EventStatus } from "./event-draft";

/**
 * An event's status as a mark and words (docs/spec/07 item 6), as Briefs show theirs: waiting for staff (a hollow
 * ring), shown to developers (a tick), not approved (a warning), cancelled (a cross).
 */
export const EVENT_CHIP: Record<EventStatus, ChipKind> = {
  draft: "pending",
  published: "completed",
  rejected: "overdue",
  cancelled: "ended",
};

export const EVENT_STATUSES = ["draft", "published", "rejected", "cancelled"] as const satisfies readonly EventStatus[];

/** A draft or published event can still be cancelled (app_cancel_event; 409 not_cancellable otherwise). */
export function cancellable(status: EventStatus): boolean {
  return status === "draft" || status === "published";
}
