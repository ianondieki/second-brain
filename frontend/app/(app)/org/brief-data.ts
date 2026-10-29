import { redirect } from "next/navigation";
import { cache } from "react";

import { forwardHeaders, serverApi } from "@/lib/api/server";

import type { Brief, BriefList } from "./briefs";
import { isUuid } from "./membership";
import { refusalOf, type Refusal } from "./refusals";

// Server-side reads for the organisation's Problems section (REQ-DIR-05), bounded like data.ts so a hung API ends in
// the route's error page. Reads only; posting and closing are the browser's calls (problems/calls.ts).

const TIMEOUT_MS = 5000;
/** Briefs per page: the plans allow 1, 5 or any number open, and closed ones stay listed. */
export const BRIEFS_PAGE_SIZE = 20;

async function options() {
  return { headers: await forwardHeaders(), signal: AbortSignal.timeout(TIMEOUT_MS), cache: "no-store" as const };
}

export type BriefsRead =
  | { kind: "ok"; value: BriefList }
  | { kind: "staleCursor" }
  | { kind: "refused"; refusal: Refusal };

/** A refusal the screen words, or a sign-in redirect when the session ended; anything unexpected is an error. */
function refused(status: number, error: unknown, path: string): { kind: "refused"; refusal: Refusal } {
  const refusal = refusalOf(status, error);
  if (refusal === "mfa_required") return { kind: "refused", refusal };
  if (status === 401) redirect("/login");
  if (refusal === "generic") throw new Error(`${path} answered ${status}`);
  return { kind: "refused", refusal };
}

/** One page of the organisation's Briefs (newest first, every state), its plan's open Briefs and the budget bands. */
export const getBriefs = cache(async function getBriefs(
  orgId: string,
  cursor?: string,
  limit = BRIEFS_PAGE_SIZE,
): Promise<BriefsRead> {
  const { data, error, response } = await serverApi().GET("/api/orgs/{org_id}/briefs", {
    params: { path: { org_id: orgId }, query: { cursor, limit } },
    ...(await options()),
  });
  if (data) return { kind: "ok", value: data };
  if (response.status === 400 && cursor) return { kind: "staleCursor" };
  return refused(response.status, error, "GET /api/orgs/{org_id}/briefs");
});

/** One of the organisation's Briefs, or null when it has none with that id (another organisation's answers 404). */
export const getBrief = cache(async function getBrief(
  orgId: string,
  briefId: string,
): Promise<{ kind: "ok"; value: Brief } | { kind: "refused"; refusal: Refusal } | null> {
  if (!isUuid(briefId)) return null;
  const { data, error, response } = await serverApi().GET("/api/orgs/{org_id}/briefs/{problem_id}", {
    params: { path: { org_id: orgId, problem_id: briefId } },
    ...(await options()),
  });
  if (data) return { kind: "ok", value: data };
  if (response.status === 404) return null;
  return refused(response.status, error, "GET /api/orgs/{org_id}/briefs/{problem_id}");
});
