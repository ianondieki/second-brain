import { api, type ApiClient } from "@/lib/api/client";

import { shortlistProblem, type ShortlistProblem } from "../shortlist";

// The browser's shortlist calls (same-origin /api, CSRF header added by the client): add (PUT, idempotent) or remove
// (DELETE, 204 whether or not it was there). Each settles into ok or a problem the screen words; a thrown fetch is
// "network".

export type ShortlistOutcome = { ok: true } | { ok: false; problem: ShortlistProblem };

export async function setShortlisted(
  orgId: string,
  proposalId: string,
  on: boolean,
  client: ApiClient = api,
): Promise<ShortlistOutcome> {
  const params = { path: { org_id: orgId, proposal_id: proposalId } };
  try {
    const { error, response } = on
      ? await client.PUT("/api/orgs/{org_id}/shortlist/{proposal_id}", { params })
      : await client.DELETE("/api/orgs/{org_id}/shortlist/{proposal_id}", { params });
    return response.ok ? { ok: true } : { ok: false, problem: shortlistProblem(response.status, error) };
  } catch {
    return { ok: false, problem: "network" };
  }
}
