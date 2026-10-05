import { redirect } from "next/navigation";

import { forwardHeaders, serverApi } from "@/lib/api/server";

import { refusalOf, type Refusal } from "./refusals";
import { compareProblem, type CompareOut, type CompareProblem, type ShortlistPage } from "./shortlist";

// Server-side reads for the shortlist and compare screens (REQ-REPO-02), bounded like data.ts so a hung API ends in
// the route's error page. Reads only.

const TIMEOUT_MS = 5000;
/** Entries per Shortlist page. */
export const SHORTLIST_PAGE_SIZE = 50;

async function options() {
  return { headers: await forwardHeaders(), signal: AbortSignal.timeout(TIMEOUT_MS), cache: "no-store" as const };
}

export type ShortlistRead =
  | { kind: "page"; page: ShortlistPage }
  | { kind: "staleCursor" }
  | { kind: "refused"; refusal: Refusal };

/** One page of the organisation's shortlist, newest first (every member reads it). */
export async function getShortlist(orgId: string, cursor?: string): Promise<ShortlistRead> {
  const { data, error, response } = await serverApi().GET("/api/orgs/{org_id}/shortlist", {
    params: { path: { org_id: orgId }, query: { cursor, limit: SHORTLIST_PAGE_SIZE } },
    ...(await options()),
  });
  if (data) return { kind: "page", page: data };
  if (response.status === 400 && cursor) return { kind: "staleCursor" };
  const refusal = refusalOf(response.status, error);
  if (refusal === "mfa_required") return { kind: "refused", refusal };
  if (response.status === 401) redirect("/login");
  if (refusal === "generic") throw new Error(`GET /api/orgs/{org_id}/shortlist answered ${response.status}`);
  return { kind: "refused", refusal };
}

/**
 * Whether the proposal is on the organisation's shortlist (the proposal and match pages' star): one read of its entry,
 * which every member may make. 404 (not on the list) and any other failure are false, so the page still renders; a lost
 * session signs in again.
 */
export async function isShortlisted(orgId: string, proposalId: string): Promise<boolean> {
  let answer;
  try {
    answer = await serverApi().GET("/api/orgs/{org_id}/shortlist/{proposal_id}", {
      params: { path: { org_id: orgId, proposal_id: proposalId } },
      ...(await options()),
    });
  } catch {
    return false;
  }
  if (answer.response.status === 401) redirect("/login");
  return answer.response.status === 200;
}

export type CompareRead =
  | { kind: "ok"; value: CompareOut }
  | { kind: "problem"; problem: CompareProblem }
  | { kind: "refused"; refusal: Refusal };

/** The proposals side by side, Tier 1 only; a 422 is the page's own sentence (count, or not on the shortlist). */
export async function getCompare(orgId: string, ids: readonly string[]): Promise<CompareRead> {
  const { data, error, response } = await serverApi().GET("/api/orgs/{org_id}/shortlist/compare", {
    params: { path: { org_id: orgId }, query: { ids: ids.join(",") } },
    ...(await options()),
  });
  if (data) return { kind: "ok", value: data };
  if (response.status === 422) return { kind: "problem", problem: compareProblem(error) };
  const refusal = refusalOf(response.status, error);
  if (refusal === "mfa_required") return { kind: "refused", refusal };
  if (response.status === 401) redirect("/login");
  if (refusal === "generic") throw new Error(`GET /api/orgs/{org_id}/shortlist/compare answered ${response.status}`);
  return { kind: "refused", refusal };
}
