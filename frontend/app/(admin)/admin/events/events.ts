import type { EventOut, EventStatus } from "@/components/events/event-draft";
import { apiErrorCode } from "@/lib/api/error-code";

// The staff events queue's pure parts (REQ-DEV-02, REQ-ADM-01; D-60; P22 card B default (1)): its views, its order and
// what a refused decision leaves. The API's message text is never shown.

export const ADMIN_EVENTS_PATH = "/admin/events";

/**
 * The queue's views: in review (drafts) first, then published, then closed (rejected or cancelled, each with its own
 * status mark). Three tabs, so the strip fits 360 px without scrolling.
 */
export const EVENT_VIEWS = ["draft", "published", "closed"] as const;
export type EventsView = (typeof EVENT_VIEWS)[number];

/** The statuses each view lists (the API filters by one status a call). */
export const VIEW_STATUSES: Record<EventsView, readonly EventStatus[]> = {
  draft: ["draft"],
  published: ["published"],
  closed: ["rejected", "cancelled"],
};

export function eventsView(value: string | undefined): EventsView {
  return (EVENT_VIEWS as readonly string[]).includes(value ?? "") ? (value as EventsView) : "draft";
}

export function eventsViewHref(view: EventsView): string {
  return view === "draft" ? ADMIN_EVENTS_PATH : `${ADMIN_EVENTS_PATH}?view=${view}`;
}

export function adminEventHref(id: string): string {
  return `${ADMIN_EVENTS_PATH}/${encodeURIComponent(id)}`;
}

/**
 * Events in review soonest first (the one starting next needs a decision first); published ones as the API sends them
 * (newest first); closed ones by their last change, newest first.
 */
export function queueOrder(view: EventsView, items: readonly EventOut[]): EventOut[] {
  const mine = items.filter((event) => VIEW_STATUSES[view].includes(event.status));
  if (view === "draft") return [...mine].sort((a, b) => Date.parse(a.starts_at) - Date.parse(b.starts_at));
  if (view === "closed") return [...mine].sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at));
  return mine;
}

export type Decision = "publish" | "reject";

/** Why a decision was refused (`eventForm.refusal.*` words each), or the step-up. */
export type DecisionRefusal =
  | { kind: "stepUp" }
  | {
      kind: "refusal";
      code: "changedSinceReview" | "eventOver" | "organisationUnavailable" | "alreadyDecided" | "notFound" | "signedOut" | "generic";
    };

export function decisionRefusalOf(status: number, error: unknown): DecisionRefusal {
  const code = apiErrorCode(error);
  if (code === "step_up_required") return { kind: "stepUp" };
  if (status === 401) return { kind: "refusal", code: "signedOut" };
  if (status === 404) return { kind: "refusal", code: "notFound" };
  if (code === "changed_since_review") return { kind: "refusal", code: "changedSinceReview" };
  if (code === "event_over") return { kind: "refusal", code: "eventOver" };
  if (code === "organisation_unavailable") return { kind: "refusal", code: "organisationUnavailable" };
  if (code === "already_decided" || status === 409) return { kind: "refusal", code: "alreadyDecided" };
  return { kind: "refusal", code: "generic" };
}

/**
 * What a refused decision leaves: the event changed, or was decided or removed meanwhile, so the page is read again
 * (the fresh version is what the next decision sends as `seen`); an event that is over or an organisation no longer
 * able to publish can only be rejected, so Reject becomes the one primary action; anything else can be tried again.
 */
export function decisionNext(code: Extract<DecisionRefusal, { kind: "refusal" }>["code"]): "reload" | "reject" | "retry" {
  if (code === "changedSinceReview" || code === "alreadyDecided" || code === "notFound") return "reload";
  if (code === "eventOver" || code === "organisationUnavailable") return "reject";
  return "retry";
}
