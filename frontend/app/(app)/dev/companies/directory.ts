import { redirect } from "next/navigation";
import { cache } from "react";

import { forwardHeaders, serverApi } from "@/lib/api/server";

import {
  browseQuery,
  isOrgId,
  type DirectoryFilters,
  type DirectoryPage,
  type FilterOptions,
  type NicheNode,
  type OrgCard,
} from "./filters";

// Server-side calls for the Companies screens (GET /api/directory/*, signed in only). Each call is bounded, so a
// hung API ends in the route's error page instead of a page that never renders.
const TIMEOUT_MS = 5000;

async function options() {
  return { headers: await forwardHeaders(), signal: AbortSignal.timeout(TIMEOUT_MS), cache: "no-store" as const };
}

function failed(path: string, status: number): never {
  // The session ended between the page's /me check and this call: sign in again.
  if (status === 401) redirect("/login");
  throw new Error(`${path} answered ${status}`);
}

export type Browse = { kind: "page"; page: DirectoryPage } | { kind: "staleCursor" };

/** One page of the directory. A cursor the API no longer accepts (400 invalid_cursor) is "start again". */
export async function browseDirectory(filters: DirectoryFilters): Promise<Browse> {
  const { data, response } = await serverApi().GET("/api/directory/orgs", {
    params: { query: browseQuery(filters) },
    ...(await options()),
  });
  if (data) return { kind: "page", page: data };
  if (response.status === 400 && filters.cursor) return { kind: "staleCursor" };
  return failed("GET /api/directory/orgs", response.status);
}

/** The niche tree and the org types and counties, for the filter selects. */
export async function directoryOptions(): Promise<{ niches: NicheNode[]; filterOptions: FilterOptions }> {
  const api = serverApi();
  const [niches, filterOptions] = await Promise.all([
    api.GET("/api/directory/niches", await options()),
    api.GET("/api/directory/filter-options", await options()),
  ]);
  if (!niches.data) failed("GET /api/directory/niches", niches.response.status);
  if (!filterOptions.data) failed("GET /api/directory/filter-options", filterOptions.response.status);
  return { niches: niches.data, filterOptions: filterOptions.data };
}

/**
 * One organisation's card, or null when it is not listed (unknown, unlisted or delisted ids all answer 404). Cached
 * per request, so the page title and the page share one call.
 */
export const getOrgCard = cache(async function getOrgCard(orgId: string): Promise<OrgCard | null> {
  if (!isOrgId(orgId)) return null;
  const { data, response } = await serverApi().GET("/api/directory/orgs/{org_id}", {
    params: { path: { org_id: orgId } },
    ...(await options()),
  });
  if (data) return data;
  if (response.status === 404) return null;
  return failed("GET /api/directory/orgs/{org_id}", response.status);
});
