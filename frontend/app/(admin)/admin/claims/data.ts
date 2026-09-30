import { serverApi } from "@/lib/api/server";

import { readOptions, settle, type Loaded } from "../load";
import type { Claim, ClaimDetail, ClaimView } from "./claims";

// Server-side reads of the claims queue, read only (REQ-DIR-03 queue; GET /api/admin/claims[/{claim_id}],
// bridge/admin/claims.py): staff admins with a fresh second factor.

export interface ClaimQueue {
  items: Claim[];
  /** Business days staff have to review a claim (policy.yaml claims.review_sla_bd). */
  reviewSlaDays: number;
}

/** One view of the queue (at most 200 claims, in the API's order). */
export async function getClaims(view: ClaimView): Promise<Loaded<ClaimQueue>> {
  const { data, error, response } = await serverApi().GET("/api/admin/claims", {
    ...(await readOptions()),
    params: { query: { view } },
  });
  const queue = data ? { items: data.items, reviewSlaDays: data.review_sla_bd } : undefined;
  return settle("GET /api/admin/claims", { data: queue, error, response });
}

/** One claim with its evidence; null when there is no such claim (the API's 404 for an unknown claim id). */
export async function getClaim(claimId: string): Promise<Loaded<ClaimDetail | null>> {
  const { data, error, response } = await serverApi().GET("/api/admin/claims/{claim_id}", {
    ...(await readOptions()),
    params: { path: { claim_id: claimId } },
  });
  if (response.status === 404) return { kind: "ok", data: null };
  return settle("GET /api/admin/claims/{claim_id}", { data, error, response });
}
