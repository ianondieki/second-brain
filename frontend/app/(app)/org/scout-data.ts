import { redirect } from "next/navigation";
import { cache } from "react";

import type { components } from "@/lib/api/schema";
import { forwardHeaders, serverApi } from "@/lib/api/server";

import { isUuid } from "./membership";
import { refusalOf, type Refusal } from "./refusals";
import type { MatchDetail, Match, Scout, ScoutList } from "./scout";

// Server-side reads for the Scout Agent screens (REQ-SCOUT-01..03), bounded like data.ts so a hung API ends in the
// route's error page. Reads only: a digest link opens these pages and nothing changes on GET (docs/spec/06 6.8).

export type NicheNode = components["schemas"]["NicheNode"];
export type County = components["schemas"]["CountyRef"];
export type Member = components["schemas"]["MemberOut"];
export type OrgVerification = components["schemas"]["OrgVerification"];

const TIMEOUT_MS = 5000;

async function options() {
  return { headers: await forwardHeaders(), signal: AbortSignal.timeout(TIMEOUT_MS), cache: "no-store" as const };
}

export type Read<T> = { kind: "ok"; value: T } | { kind: "refused"; refusal: Refusal };

/** A refusal the screen words, or a sign-in redirect when the session ended; anything unexpected is an error. */
function refused<T>(status: number, error: unknown, path: string): Read<T> {
  const refusal = refusalOf(status, error);
  if (refusal === "mfa_required") return { kind: "refused", refusal };
  if (status === 401) redirect("/login");
  if (refusal === "generic") throw new Error(`${path} answered ${status}`);
  return { kind: "refused", refusal };
}

/** The organisation's scouts, what its plan allows and the budget bands (any member). */
export const getScouts = cache(async function getScouts(orgId: string): Promise<Read<ScoutList>> {
  const { data, error, response } = await serverApi().GET("/api/orgs/{org_id}/scouts", {
    params: { path: { org_id: orgId } },
    ...(await options()),
  });
  if (data) return { kind: "ok", value: data };
  return refused(response.status, error, "GET /api/orgs/{org_id}/scouts");
});

/** One scout of the organisation, or null when it has none with that id. */
export async function getScout(orgId: string, scoutId: string): Promise<Read<Scout> | null> {
  if (!isUuid(scoutId)) return null;
  const { data, error, response } = await serverApi().GET("/api/orgs/{org_id}/scouts/{scout_id}", {
    params: { path: { org_id: orgId, scout_id: scoutId } },
    ...(await options()),
  });
  if (data) return { kind: "ok", value: data };
  if (response.status === 404) return null;
  return refused(response.status, error, "GET /api/orgs/{org_id}/scouts/{scout_id}");
}

/** The organisation's scout matches, newest first (the API returns at most 200). */
export async function getMatches(orgId: string): Promise<Read<Match[]>> {
  const { data, error, response } = await serverApi().GET("/api/orgs/{org_id}/matches", {
    params: { path: { org_id: orgId } },
    ...(await options()),
  });
  if (data) return { kind: "ok", value: data.items };
  return refused(response.status, error, "GET /api/orgs/{org_id}/matches");
}

/** One match with its rules, the organisation's engagement and the Express interest state; null when not found. */
export const getMatch = cache(async function getMatch(
  orgId: string,
  matchId: string,
): Promise<Read<MatchDetail> | null> {
  if (!isUuid(matchId)) return null;
  const { data, error, response } = await serverApi().GET("/api/orgs/{org_id}/matches/{match_id}", {
    params: { path: { org_id: orgId, match_id: matchId } },
    ...(await options()),
  });
  if (data) return { kind: "ok", value: data };
  if (response.status === 404) return null;
  return refused(response.status, error, "GET /api/orgs/{org_id}/matches/{match_id}");
});

/** The niche tree (active niches: a parent and the niches under it). */
export async function getNicheTree(): Promise<NicheNode[]> {
  const { data, response } = await serverApi().GET("/api/directory/niches", await options());
  if (data) return data;
  if (response.status === 401) redirect("/login");
  throw new Error(`GET /api/directory/niches answered ${response.status}`);
}

/** Kenya's counties, as the directory's filters list them. */
export async function getCounties(): Promise<County[]> {
  const { data, response } = await serverApi().GET("/api/directory/filter-options", await options());
  if (data) return data.counties;
  if (response.status === 401) redirect("/login");
  throw new Error(`GET /api/directory/filter-options answered ${response.status}`);
}

/** The organisation's active members with their roles, or null when they could not be read. */
export async function getMembers(orgId: string): Promise<Member[] | null> {
  const { data, response } = await serverApi().GET("/api/orgs/{org_id}/members", {
    params: { path: { org_id: orgId } },
    ...(await options()),
  });
  if (response.status === 401) redirect("/login");
  return data ?? null;
}

/** The organisation's verification level, or null when it could not be read. */
export async function getVerification(orgId: string): Promise<OrgVerification | null> {
  const { data, response } = await serverApi().GET("/api/orgs/{org_id}", {
    params: { path: { org_id: orgId } },
    ...(await options()),
  });
  if (response.status === 401) redirect("/login");
  return data?.verification ?? null;
}

/**
 * The organisation plans (limits, upgrade ladder), or null when they could not be read: never taken as "no plan to
 * move to" (the Problems section's full-plan notice says the choices could not be loaded instead).
 */
export async function readOrgPlans(): Promise<components["schemas"]["PlanOut"][] | null> {
  const { data, response } = await serverApi().GET("/api/plans", {
    params: { query: { side: "org" } },
    ...(await options()),
  });
  if (response.status === 401) redirect("/login");
  return data?.plans ?? null;
}

/** The organisation plans, or an empty list when they could not be read (the scout form offers no upgrade then). */
export async function getOrgPlans(): Promise<components["schemas"]["PlanOut"][]> {
  return (await readOrgPlans()) ?? [];
}
