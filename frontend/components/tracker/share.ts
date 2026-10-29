import { api, type ApiClient } from "@/lib/api/client";
import { apiErrorCode } from "@/lib/api/error-code";
import type { components } from "@/lib/api/schema";

import type { Detail } from "./model";

// The developer's manual Tier-2 share on an organisation-origin engagement (REQ-ENG-04; docs/spec/06 6.9 stage 0:
// "Tier 2 by manual grant"): POST /api/engagements/{id}/share-tier2, with a fresh second factor.

export type Tier2Share = components["schemas"]["Tier2ShareOut"];

/** Engagements an organisation opened (a scout match or Browse): the developer shares the full proposal by hand. */
export const SHARE_ORIGINS: ReadonlySet<Detail["origin"]> = new Set(["org_agent_match", "org_browse"]);

/** Why a share was refused, as the screen words it (`tier2Share.refusal.*`); "stepUp" opens the code form. */
export type ShareRefusal =
  | "stepUp"
  | "notAllowed"
  | "notApplicable"
  | "ended"
  | "unavailable"
  | "mfaSetup"
  | "notFound"
  | "network"
  | "generic";

const BY_CODE: Record<string, ShareRefusal> = {
  step_up_required: "stepUp",
  not_your_action: "notAllowed",
  share_not_applicable: "notApplicable",
  engagement_ended: "ended",
  proposal_unavailable: "unavailable",
  mfa_enrolment_required: "mfaSetup",
};

export function shareRefusalOf(status: number, error: unknown): ShareRefusal {
  const code = apiErrorCode(error);
  if (code && code in BY_CODE) return BY_CODE[code];
  if (status === 404) return "notFound";
  return "generic";
}

export type ShareOutcome = { ok: true; share: Tier2Share } | { ok: false; refusal: ShareRefusal };

/** Shares the full proposal (idempotent: an existing share comes back as it is). */
export async function shareTier2(engagementId: string, client: ApiClient = api): Promise<ShareOutcome> {
  try {
    const { data, error, response } = await client.POST("/api/engagements/{engagement_id}/share-tier2", {
      params: { path: { engagement_id: engagementId } },
    });
    if (data) return { ok: true, share: data };
    return { ok: false, refusal: shareRefusalOf(response.status, error) };
  } catch {
    return { ok: false, refusal: "network" };
  }
}
