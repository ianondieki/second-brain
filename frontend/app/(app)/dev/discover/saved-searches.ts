import { apiErrorCode } from "@/lib/api/error-code";
import type { components } from "@/lib/api/schema";

import type { DiscoverQuery, View } from "./discover";

// Saved Discover searches (REQ-PERS-03, REQ-TREND-02; P21 track C, D-57 (7)): the plain logic of the "Save this search"
// form and the Saved searches panel. The API decides; this only words it. Nothing here calls the API.

type Schemas = components["schemas"];
export type SavedSearch = Schemas["SavedSearchOut"];
export type SavedSearchList = Schemas["SavedSearchList"];
export type SavedSearchIn = Schemas["SavedSearchIn"];

/** The lists a search can be saved for (the API's `view`). */
export type SavedView = SavedSearch["view"];
export const SAVED_VIEWS: readonly SavedView[] = ["problems", "briefs"];
/** The longest name the API takes. */
export const MAX_NAME = 60;

export function savesView(view: View): view is SavedView {
  return (SAVED_VIEWS as readonly string[]).includes(view);
}

/** One saved search as the panel shows it: its name, the link that applies it and its filters in words. */
export interface SavedSearchRow {
  id: string;
  name: string;
  alerts: boolean;
  /** Discover with the saved view and filters (tap to apply). */
  href: string;
  /** The view and filters in words, in order: the list, the niche, the county, the words in quotes. */
  facts: string[];
}

/** The body of POST /api/me/saved-searches for the current view and filters. */
export function saveBody(query: DiscoverQuery & { view: SavedView }, name: string, alerts: boolean): SavedSearchIn {
  return {
    name: name.trim(),
    view: query.view,
    niche: query.niche ?? null,
    county: query.county ?? null,
    words: query.words ?? null,
    alerts,
  };
}

/** What is wrong with a name before it is sent (`savedSearches.problem.*`), or null. */
export function nameProblem(name: string): "nameMissing" | "nameLong" | null {
  const trimmed = name.trim();
  if (!trimmed) return "nameMissing";
  if (trimmed.length > MAX_NAME) return "nameLong";
  return null;
}

/** Why a save, a change or a delete was refused (`savedSearches.problem.*`); a thrown fetch is "network". */
export type SavedProblem = "nameMissing" | "nameLong" | "limit" | "unknown" | "signedOut" | "network" | "failed";

export function savedProblem(status: number, body: unknown): SavedProblem {
  if (status === 0) return "network";
  if (status === 401) return "signedOut";
  const code = apiErrorCode(body);
  if (status === 409 && code === "saved_searches_limit") return "limit";
  if (status === 422 && (code === "unknown_niche" || code === "unknown_county")) return "unknown";
  return "failed";
}
