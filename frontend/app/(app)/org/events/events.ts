import { postsBriefs } from "../briefs";
import { orgQuery, type Membership } from "../membership";

// The organisation's Events section (REQ-DEV-02; D-60; P22 card B defaults (1) and (6)): its links and who posts.

export const EVENTS_PATH = "/org/events";

/** The organisation's events. */
export function eventsHref(memberships: readonly Membership[], orgId: string): string {
  return `${EVENTS_PATH}${orgQuery(memberships, orgId)}`;
}

/** One of its events. */
export function orgEventHref(memberships: readonly Membership[], orgId: string, eventId: string): string {
  return `${EVENTS_PATH}/${encodeURIComponent(eventId)}${orgQuery(memberships, orgId)}`;
}

/** The "Post an event" form. */
export function newEventHref(memberships: readonly Membership[], orgId: string): string {
  return `${EVENTS_PATH}/new${orgQuery(memberships, orgId)}`;
}

/**
 * Who posts and cancels events: the Briefs' editors (owner, admin, signatory, reviewer; bridge/problems/brief_rules.py
 * EDITORS, which the events API reuses), of an E2 organisation. Every member reads them. This only decides what is
 * offered; the API answers 403 to anyone else.
 */
export function postsEvents(membership: Membership): boolean {
  return postsBriefs(membership);
}
