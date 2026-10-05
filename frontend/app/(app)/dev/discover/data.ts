import { redirect } from "next/navigation";

import { forwardHeaders, serverApi } from "@/lib/api/server";

import { MAX_ITEMS, searchQuery, trendQuery, type DiscoverBriefsOut, type DiscoverQuery, type OpportunityGapOut, type TrendingOut } from "./discover";
import type { LikedNiches, Recommendations } from "./recommendations";
import type { SavedSearchList } from "./saved-searches";

// Server-side calls for Discover, "Recommended for you" and the liked-niches page (REQ-TREND-02, REQ-PERS-01; signed
// in only). Each call is bounded, so a hung API ends in the route's error page instead of a page that never renders.
const TIMEOUT_MS = 8000; // trends are computed on each request (about 1 s at 50k events, REQ-TREND-01 card)

async function options() {
  return { headers: await forwardHeaders(), signal: AbortSignal.timeout(TIMEOUT_MS), cache: "no-store" as const };
}

function failed(path: string, status: number): never {
  // The session ended between the page's /me check and this call: sign in again.
  if (status === 401) redirect("/login");
  throw new Error(`${path} answered ${status}`);
}

/** Trending and new problems and projects, filtered by niche and county. */
export async function trending(query: DiscoverQuery): Promise<TrendingOut> {
  const { data, response } = await serverApi().GET("/api/discover/trending", {
    params: { query: searchQuery(query) },
    ...(await options()),
  });
  if (!data) failed("GET /api/discover/trending", response.status);
  return data;
}

/** Rising problems with fewer than 3 proposals. */
export async function opportunityGap(query: DiscoverQuery): Promise<OpportunityGapOut> {
  const { data, response } = await serverApi().GET("/api/discover/opportunity-gap", {
    params: { query: trendQuery(query) },
    ...(await options()),
  });
  if (!data) failed("GET /api/discover/opportunity-gap", response.status);
  return data;
}

/** Verified organisations' published, open Problem Briefs, newest first (REQ-DIR-05). */
export async function briefs(query: DiscoverQuery): Promise<DiscoverBriefsOut> {
  const { data, response } = await serverApi().GET("/api/discover/briefs", {
    params: { query: { ...searchQuery(query), limit: MAX_ITEMS } },
    ...(await options()),
  });
  if (!data) failed("GET /api/discover/briefs", response.status);
  return data;
}

/**
 * "Recommended for you", or null when they cannot be shown (no developer profile, a failing ranker, no answer in
 * time, the network): Home still renders, and says so, rather than failing as a whole. Only a lost session (401)
 * leaves Home, to sign in again.
 */
export async function recommendations(): Promise<Recommendations | null> {
  let answer;
  try {
    answer = await serverApi().GET("/api/me/recommendations", await options());
  } catch {
    return null;
  }
  if (answer.data) return answer.data;
  if (answer.response.status === 401) redirect("/login");
  return null;
}

/** The developer's liked niches with the allowed range; null without a developer profile. */
export async function likedNiches(): Promise<LikedNiches | null> {
  const { data, response } = await serverApi().GET("/api/me/niches", await options());
  if (data) return data;
  if (response.status === 404) return null;
  return failed("GET /api/me/niches", response.status);
}

export type ConsentItem = { purpose: string; granted: boolean; text: string; version: string };

/** The profiling consent as the settings show it (the API's own wording and version), or null when it is not offered. */
export async function profilingConsent(): Promise<ConsentItem | null> {
  const { data, response } = await serverApi().GET("/api/me/consents", await options());
  if (!data) failed("GET /api/me/consents", response.status);
  return data.find((item) => item.purpose === "profiling") ?? null;
}

/** The developer's saved Discover searches with the cap, or null without a developer profile (404). */
export async function savedSearches(): Promise<SavedSearchList | null> {
  const { data, response } = await serverApi().GET("/api/me/saved-searches", await options());
  if (data) return data;
  if (response.status === 404) return null;
  return failed("GET /api/me/saved-searches", response.status);
}
