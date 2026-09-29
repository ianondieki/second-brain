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
 * The membership a screen acts for: the one named by `requested` when the person is a member of it, else their
 * first membership (the API lists them by name). Null for an account without an active membership.
 */
export function pickMembership(memberships: readonly Membership[], requested: SearchValue): Membership | null {
  const wanted = first(requested)?.toLowerCase();
  return memberships.find((m) => m.org_id.toLowerCase() === wanted) ?? memberships[0] ?? null;
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
