import { api } from "@/lib/api/client";

import { scoutRefusalOf, type Preview, type Scout, type ScoutBody, type ScoutRefusal } from "../../scout";

// The scout form's calls from the browser (same-origin /api; the typed client adds the CSRF header). Each settles into
// its value or a refusal the form words from locales, with the next plan up for a 402.

export type Refused = { ok: false; refusal: ScoutRefusal; upgradePlan: string | null };
export type Outcome<T> = { ok: true; value: T } | Refused;

const NETWORK: Refused = { ok: false, refusal: "network", upgradePlan: null };

async function settle<T>(call: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<Outcome<T>> {
  try {
    const { data, error, response } = await call;
    if (data !== undefined && response.ok) return { ok: true, value: data };
    return { ok: false, ...scoutRefusalOf(response.status, error) };
  } catch {
    return NETWORK;
  }
}

export interface ScoutCalls {
  preview: (orgId: string, body: ScoutBody) => Promise<Outcome<Preview>>;
  create: (orgId: string, body: ScoutBody) => Promise<Outcome<Scout>>;
  update: (orgId: string, scoutId: string, body: ScoutBody | { paused: boolean }) => Promise<Outcome<Scout>>;
}

export const scoutCalls: ScoutCalls = {
  preview: (orgId, body) =>
    settle(api.POST("/api/orgs/{org_id}/scouts/preview", { params: { path: { org_id: orgId } }, body })),
  create: (orgId, body) => settle(api.POST("/api/orgs/{org_id}/scouts", { params: { path: { org_id: orgId } }, body })),
  update: (orgId, scoutId, body) =>
    settle(
      api.PATCH("/api/orgs/{org_id}/scouts/{scout_id}", {
        params: { path: { org_id: orgId, scout_id: scoutId } },
        body,
      }),
    ),
};
