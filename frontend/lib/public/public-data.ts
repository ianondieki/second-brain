import { forwardHeaders, serverApi } from "@/lib/api/server";
import type { components } from "@/lib/api/schema";

// The public reads (P24; REQ-UX-03): GET /api/public/activity, /api/public/explore and /api/public/problems/{id}. No
// session cookie, the visitor's forwarded address for the API's per-address limit, bounded so a slow API leaves the
// section out rather than holding the page. A failed summary is null: the caller leaves its section out (or, on
// Explore, shows its empty state).

type Schemas = components["schemas"];
export type PublicActivity = Schemas["ActivityFeed"];
export type ActivityItem = Schemas["ActivityItem"];
export type ActivityKind = ActivityItem["kind"];
export type PublicExplore = Schemas["Explore"];
export type ExploreTeaser = Schemas["ExploreTeaser"];
export type ExploreCounty = Schemas["ExploreCounty"];
export type ExploreNiche = Schemas["ExploreNiche"];
export type PublicProblem = Schemas["PublicProblem"];

const ACTIVITY_KINDS: ReadonlySet<string> = new Set<ActivityKind>(["problem_posted", "version_registered", "brief_opened"]);

const bounded = async () => ({ headers: await forwardHeaders({ session: false }), signal: AbortSignal.timeout(4000), cache: "no-store" as const });

/** The last public events, newest first, without any kind this page does not know; null when the read fails or none is left. */
export async function publicActivity(): Promise<PublicActivity | null> {
  try {
    const { data } = await serverApi().GET("/api/public/activity", await bounded());
    if (!data || !Array.isArray(data.items)) return null;
    const items = data.items.filter((item) => ACTIVITY_KINDS.has(item.kind));
    return items.length > 0 ? { ...data, items } : null;
  } catch {
    return null;
  }
}

/** Published problems by county and by niche; null when the read fails. */
export async function publicExplore(): Promise<PublicExplore | null> {
  try {
    const { data } = await serverApi().GET("/api/public/explore", await bounded());
    return data && Array.isArray(data.counties) && Array.isArray(data.niches) ? data : null;
  } catch {
    return null;
  }
}

export type ProblemRead = { kind: "found"; problem: PublicProblem } | { kind: "notFound" } | { kind: "unavailable" };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** One public problem: found, not public (404, or an id that cannot be one: no request), or the API did not answer. */
export async function publicProblem(id: string): Promise<ProblemRead> {
  if (!UUID.test(id)) return { kind: "notFound" };
  try {
    const { data, response } = await serverApi().GET("/api/public/problems/{problem_id}", {
      params: { path: { problem_id: id } },
      ...(await bounded()),
    });
    if (data) return { kind: "found", problem: data };
    return response.status === 404 || response.status === 422 ? { kind: "notFound" } : { kind: "unavailable" };
  } catch {
    return { kind: "unavailable" };
  }
}

/** "ICT › Networks & Telecommunications", or the top-level niche alone. */
export function nicheLabel(niche: PublicProblem["niche"]): string | null {
  if (!niche) return null;
  return niche.parent ? `${niche.parent.name} › ${niche.name}` : niche.name;
}
