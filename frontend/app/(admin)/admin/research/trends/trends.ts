import { apiErrorCode } from "@/lib/api/error-code";
import type { components } from "@/lib/api/schema";

// The research page's trend cards (REQ-DEV-02; D-60; P22 card B default (5)): their addresses and which fixed sentence
// a refused decision gets (adminResearch.trends.refusal.*). The API's message text is never shown.

export type TrendCandidate = components["schemas"]["TrendCardAdminOut"];
export type TrendCardDetail = components["schemas"]["TrendCardAdminDetailOut"];

export function trendReviewHref(id: string): string {
  return `/admin/research/trends/${encodeURIComponent(id)}`;
}

/** A card the model did not draft (no LLM trace: the demo's hand-written cards) is labelled as a seeded example. */
export function seededTrend(card: Pick<TrendCandidate, "llm_trace_id">): boolean {
  return card.llm_trace_id === null;
}

export type TrendRefusalCode = "unsourced_name" | "already_decided" | "not_found" | "generic";
export type TrendRefusal = { kind: "stepUp" } | { kind: "refusal"; code: TrendRefusalCode };

export function trendRefusalOf(status: number, error: unknown): TrendRefusal {
  const code = apiErrorCode(error);
  if (code === "step_up_required") return { kind: "stepUp" };
  if (status === 404) return { kind: "refusal", code: "not_found" };
  if (code === "unsourced_name" || code === "already_decided") return { kind: "refusal", code };
  return { kind: "refusal", code: "generic" };
}
