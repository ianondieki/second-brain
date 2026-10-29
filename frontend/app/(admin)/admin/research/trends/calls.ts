import { api, type ApiClient } from "@/lib/api/client";

import { trendRefusalOf, type TrendRefusal } from "./trends";

// The trend cards' browser calls (REQ-DEV-02; /api/admin/research/trends/{id}/decision and /trend-runs), settling
// into their answer or a refusal, never a thrown error.

export type TrendOutcome = { ok: true } | { ok: false; refusal: TrendRefusal };
export type TrendDecision = "publish" | "reject";

export interface TrendCalls {
  decide: (cardId: string, decision: TrendDecision) => Promise<TrendOutcome>;
  /** Draft this week's trends now (the weekly task, queued). */
  draft: () => Promise<TrendOutcome>;
}

async function settle(call: Promise<{ error?: unknown; response: Response }>): Promise<TrendOutcome> {
  try {
    const { error, response } = await call;
    return response.ok ? { ok: true } : { ok: false, refusal: trendRefusalOf(response.status, error) };
  } catch {
    return { ok: false, refusal: { kind: "refusal", code: "generic" } };
  }
}

export function trendCalls(client: ApiClient = api): TrendCalls {
  return {
    decide: (cardId, decision) =>
      settle(client.POST("/api/admin/research/trends/{card_id}/decision", { params: { path: { card_id: cardId } }, body: { decision } })),
    draft: () => settle(client.POST("/api/admin/research/trend-runs")),
  };
}
