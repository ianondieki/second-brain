import { redirect } from "next/navigation";

import { forwardHeaders, serverApi } from "@/lib/api/server";

import { refusalOf, type Refusal } from "../refusals";
import type { OrgTeam } from "./team";

// The Team page's server reads (REQ-TEN-02), each bounded so a hung API ends in the route's error page. The session
// cookie is forwarded; the organisation is always one of the person's memberships (../data.ts orgContext).

const TIMEOUT_MS = 5000;

async function options() {
  return { headers: await forwardHeaders(), signal: AbortSignal.timeout(TIMEOUT_MS), cache: "no-store" as const };
}

export type TeamRead = { kind: "ok"; team: OrgTeam } | { kind: "refused"; refusal: Refusal };

/** GET /api/orgs/{org_id}/team: the roster, open invitations (owners and admins), niche defaults, escalation contact. */
export async function getTeam(orgId: string): Promise<TeamRead> {
  const { data, error, response } = await serverApi().GET("/api/orgs/{org_id}/team", {
    params: { path: { org_id: orgId } },
    ...(await options()),
  });
  if (data) return { kind: "ok", team: data };
  if (response.status === 401 && refusalOf(response.status, error) !== "mfa_required") redirect("/login");
  if (response.status >= 500) throw new Error(`GET /api/orgs/{org_id}/team answered ${response.status}`);
  return { kind: "refused", refusal: refusalOf(response.status, error) };
}

/**
 * The organisation's niches as its directory card lists them ({slug, label}), or [] when it has no card (an organisation
 * that is not listed) or the card cannot be read: the defaults already set are still shown (team.ts nicheRows).
 */
export async function getOrgNiches(orgId: string): Promise<{ slug: string; label: string }[]> {
  try {
    const { data } = await serverApi().GET("/api/directory/orgs/{org_id}", {
      params: { path: { org_id: orgId } },
      ...(await options()),
    });
    return data?.niches.map(({ slug, label }) => ({ slug, label })) ?? [];
  } catch {
    return [];
  }
}
