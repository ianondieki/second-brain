import { forwardHeaders } from "@/lib/api/server";

// The two public summaries (P24-B; REQ-UX-03): GET /api/public/activity and GET /api/public/explore. Public reads: no
// session cookie, the visitor's forwarded address for the API's per-address limit, bounded so a slow API leaves the
// section out rather than holding the page. Any failure is null: the caller leaves its section out (or, on Explore,
// shows its empty state).
//
// PROVISIONAL (until P24-B merges): the shapes below follow the P24 brief and are read with a plain fetch; on merge
// they become the generated `components["schemas"][…]` types and `serverApi().GET(…)` (npm run api:types).

export type ActivityKind = "problem_posted" | "version_registered" | "stage_reached" | "brief_opened";

export interface ActivityItem {
  id: string;
  kind: ActivityKind;
  at: string;
  county: string | null;
  niche: string | null;
  title: string | null;
  stage: string | null;
  seeded: boolean;
}

export interface PublicActivity {
  generated_at: string;
  seeded: boolean;
  items: ActivityItem[];
}

export interface ExploreTeaser {
  id: string;
  title: string;
  niche: string;
  posted_at: string;
}

export interface ExploreCounty {
  code: string;
  name: string;
  count: number;
  newest: ExploreTeaser[];
}

export interface ExploreNiche {
  id: string;
  name: string;
  count: number;
  newest: ExploreTeaser[];
}

export interface PublicExplore {
  totals: { problems: number; counties: number; niches: number };
  counties: ExploreCounty[];
  niches: ExploreNiche[];
}

const apiOrigin = process.env.API_ORIGIN ?? "http://127.0.0.1:8000";

async function publicRead<T>(path: string): Promise<T | null> {
  try {
    const response = await fetch(`${apiOrigin}${path}`, {
      headers: await forwardHeaders({ session: false }),
      signal: AbortSignal.timeout(4000),
      cache: "no-store",
    });
    if (!response.ok) return null;
    return (await response.json()) as T;
  } catch {
    return null;
  }
}

/** The last public events, newest first; null when the read fails or there is nothing to show. */
export async function publicActivity(): Promise<PublicActivity | null> {
  const activity = await publicRead<PublicActivity>("/api/public/activity");
  return activity && Array.isArray(activity.items) && activity.items.length > 0 ? activity : null;
}

/** Published problems by county and by niche; null when the read fails. */
export async function publicExplore(): Promise<PublicExplore | null> {
  const explore = await publicRead<PublicExplore>("/api/public/explore");
  return explore && Array.isArray(explore.counties) && Array.isArray(explore.niches) ? explore : null;
}
