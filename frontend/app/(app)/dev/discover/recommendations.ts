import type { components } from "@/lib/api/schema";

// "Recommended for you" (REQ-PERS-01; docs/spec/06 6.7, docs/spec/07 item 2): types and pure helpers for Home's list.

type Schemas = components["schemas"];
export type Recommendations = Schemas["RecommendationsOut"];
export type Recommendation = Schemas["Recommendation"];
export type Decision = Schemas["PursuitOut"]["decision"];
export type FitLabel = Recommendation["label"];
export type LikedNiches = Schemas["LikedNichesOut"];
export type NicheOut = Schemas["NicheOut"];

/** How many recommendations Home shows (docs/spec/04 4.6: uncluttered; the rest are a Discover away). */
export const HOME_RECOMMENDATIONS = 3;

/** Message keys for the fit label the API sends in English ("Strong fit" …), so the chip can be translated. */
export const FIT_KEY = {
  "Strong fit": "strong",
  "Good fit": "good",
  Stretch: "stretch",
} as const satisfies Record<FitLabel, string>;

/** Message keys for the pursuit decision ("not_now" → "notNow"). */
export const DECISION_KEY = {
  pursue: "pursue",
  consider: "consider",
  not_now: "notNow",
} as const satisfies Record<Decision, string>;

/** Which of the three things Home's section shows. */
export type RecommendationsState =
  | { kind: "unavailable" }
  | { kind: "noNiches" }
  | { kind: "empty"; personalised: boolean }
  | { kind: "list"; personalised: boolean; items: Recommendation[]; more: boolean };

/**
 * No liked niches: the picker prompt instead of a list (the ranker needs 3 to 5 to rank on). No cards yet: the empty
 * state. Otherwise the first few, in the ranker's order.
 */
export function recommendationsState(answer: Recommendations | null): RecommendationsState {
  if (!answer) return { kind: "unavailable" };
  if (answer.liked_niches.length === 0) return { kind: "noNiches" };
  if (answer.items.length === 0) return { kind: "empty", personalised: answer.personalised };
  const items = [...answer.items].sort((a, b) => a.position - b.position);
  return {
    kind: "list",
    personalised: answer.personalised,
    items: items.slice(0, HOME_RECOMMENDATIONS),
    more: items.length > HOME_RECOMMENDATIONS,
  };
}

/** The card's one Why chip beside the pursuit chip (docs/spec/07 item 2: at most two chips). */
export function leadWhy(item: Recommendation): string | null {
  return item.why[0] ?? null;
}
