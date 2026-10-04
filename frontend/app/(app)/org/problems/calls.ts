import { api } from "@/lib/api/client";

import { briefRefusalOf, NETWORK, type Brief, type BriefBody, type Refused } from "../brief-draft";

// The Problems section's calls from the browser (same-origin /api; the typed client adds the CSRF header). Each settles
// into its value or a refusal the form words from locales: the next plan up for a 402, the fields for a 422.

export type Outcome<T> = { ok: true; value: T } | Refused;

async function settle<T>(call: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<Outcome<T>> {
  try {
    const { data, error, response } = await call;
    if (data !== undefined && response.ok) return { ok: true, value: data };
    return briefRefusalOf(response.status, error);
  } catch {
    return NETWORK;
  }
}

export interface BriefCalls {
  create: (orgId: string, body: BriefBody) => Promise<Outcome<Brief>>;
  close: (orgId: string, briefId: string) => Promise<Outcome<Brief>>;
}

export const briefCalls: BriefCalls = {
  create: (orgId, body) => settle(api.POST("/api/orgs/{org_id}/briefs", { params: { path: { org_id: orgId } }, body })),
  close: (orgId, briefId) =>
    settle(
      api.POST("/api/orgs/{org_id}/briefs/{problem_id}/close", {
        params: { path: { org_id: orgId, problem_id: briefId } },
      }),
    ),
};
