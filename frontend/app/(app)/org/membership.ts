import type { components } from "@/lib/api/schema";

export type Membership = components["schemas"]["MembershipOut"];

// Which organisation an organisation screen acts for (REQ-PROP-03 Inbox, REQ-REPO-01 proposal page). Most members
// belong to one organisation; a member of several picks one, carried as ?org=<id> in every organisation link.

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** True for a UUID in its canonical text form (path and query values are checked before they reach the API). */
export function isUuid(value: string | undefined): value is string {
  return value !== undefined && UUID.test(value);
}

type SearchValue = string | string[] | undefined;

export function first(value: SearchValue): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

/**
 * The membership a screen acts for. Without `?org=`: the person's first membership (the API lists them by name), or
 * "none" for an account without one. With `?org=`: that organisation when the person is a member of it, else
 * "notMember" (never a silent switch to another organisation, so nothing is accepted in the wrong one's name).
 */
export type Picked = { kind: "member"; membership: Membership } | { kind: "none" } | { kind: "notMember" };

export function pickMembership(memberships: readonly Membership[], requested: SearchValue): Picked {
  const wanted = first(requested)?.trim().toLowerCase();
  if (wanted) {
    const found = memberships.find((m) => m.org_id.toLowerCase() === wanted);
    return found ? { kind: "member", membership: found } : { kind: "notMember" };
  }
  return memberships[0] ? { kind: "member", membership: memberships[0] } : { kind: "none" };
}

/**
 * A link's query for the chosen organisation and any other values, or "" when there is nothing to carry. The
 * organisation is named only when the person has several, so single-organisation URLs stay short.
 */
export function orgQuery(
  memberships: readonly Membership[],
  orgId: string,
  extra: Record<string, string | undefined> = {},
): string {
  const params = new URLSearchParams();
  if (memberships.length > 1) params.set("org", orgId);
  for (const [key, value] of Object.entries(extra)) if (value) params.set(key, value);
  const query = params.toString();
  return query ? `?${query}` : "";
}

export const INBOX_PATH = "/org/inbox";

/** The Inbox of the chosen organisation, optionally at a later page. */
export function inboxHref(memberships: readonly Membership[], orgId: string, cursor?: string): string {
  return `${INBOX_PATH}${orgQuery(memberships, orgId, { cursor })}`;
}

/** A proposal's page for the chosen organisation; `view` opens the marked full proposal. */
export function proposalHref(
  memberships: readonly Membership[],
  orgId: string,
  proposalId: string,
  { view = false }: { view?: boolean } = {},
): string {
  return `${INBOX_PATH}/${encodeURIComponent(proposalId)}${orgQuery(memberships, orgId, { view: view ? "full" : undefined })}`;
}
