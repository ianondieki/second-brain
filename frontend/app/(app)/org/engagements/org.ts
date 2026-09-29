import type { Me } from "@/lib/auth/routing";

// Which organisation the Engagements list acts for: the one named by ?org= when the person is a member of it, else
// their first membership (the API lists them by name). The same rule as the org Inbox (REQ-REPO-01's membership.ts,
// which this reuses once both are on the integration branch).

type Membership = Me["memberships"][number];

export function pickOrg(memberships: readonly Membership[], requested: string | string[] | undefined): Membership | null {
  const wanted = (Array.isArray(requested) ? requested[0] : requested)?.toLowerCase();
  return memberships.find((m) => m.org_id.toLowerCase() === wanted) ?? memberships[0] ?? null;
}

export const ORG_ENGAGEMENTS_PATH = "/org/engagements";
