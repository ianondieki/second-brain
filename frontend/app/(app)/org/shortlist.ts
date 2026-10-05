import { apiErrorCode } from "@/lib/api/error-code";
import type { components } from "@/lib/api/schema";

import { INBOX_PATH, isUuid, orgQuery, type Membership } from "./membership";

// The organisation shortlist's plain logic (REQ-REPO-02, P21 track B, D-57 (5)-(6)): who may change it, its addresses,
// the compare page's ids and the fixed sentence each API refusal maps to. Nothing here calls the API.

type Schemas = components["schemas"];
export type ShortlistEntry = Schemas["ShortlistEntry"];
export type ShortlistPage = Schemas["ShortlistPage"];
export type CompareItem = Schemas["CompareItem"];
export type CompareOut = Schemas["CompareOut"];

export const SHORTLIST_PATH = `${INBOX_PATH}/shortlist`;
export const COMPARE_PATH = `${SHORTLIST_PATH}/compare`;
export const COMPARE_MIN = 2;
export const COMPARE_MAX = 4;

/** The roles that add to and remove from the shortlist (the API's EDITOR_ROLES); every member reads it. */
const EDITOR_ROLES: readonly string[] = ["admin", "reviewer", "signatory"];

export function editsShortlist(membership: Pick<Membership, "roles">): boolean {
  return membership.roles.some((role) => EDITOR_ROLES.includes(role));
}

/** The Inbox's Shortlist view for the chosen organisation, optionally at a later page. */
export function shortlistHref(memberships: readonly Membership[], orgId: string, cursor?: string): string {
  return `${SHORTLIST_PATH}${orgQuery(memberships, orgId, { cursor })}`;
}

/** The compare page without ids (the Shortlist's form adds them), keeping ?org= for members of several. */
export function compareAction(memberships: readonly Membership[], orgId: string): string {
  return `${COMPARE_PATH}${orgQuery(memberships, orgId)}`;
}

export type CompareIds = { kind: "ok"; ids: string[] } | { kind: "count"; ids: string[] };

/**
 * The proposals to compare from `?ids=`: comma-separated (the page's own links) or repeated (the shortlist's form
 * without script), ids only, each once, in the order given. Fewer than 2 or more than 4 is "count": the page says how
 * many to choose instead of asking the API.
 */
export function parseCompareIds(value: string | string[] | undefined): CompareIds {
  const raw = (Array.isArray(value) ? value : value === undefined ? [] : [value]).flatMap((part) => part.split(","));
  const ids: string[] = [];
  for (const part of raw) {
    const id = part.trim().toLowerCase();
    if (isUuid(id) && !ids.includes(id)) ids.push(id);
  }
  return ids.length >= COMPARE_MIN && ids.length <= COMPARE_MAX ? { kind: "ok", ids } : { kind: "count", ids };
}

/** Why a shortlist change was refused, as one of the toggle's fixed sentences (`shortlist.problem.*`). */
export type ShortlistProblem = "code" | "signedOut" | "role" | "gone" | "network" | "failed";

export function shortlistProblem(status: number, body: unknown): ShortlistProblem {
  if (status === 0) return "network";
  if (status === 401) return apiErrorCode(body) === "mfa_required" ? "code" : "signedOut";
  if (status === 403) return "role";
  if (status === 404) return "gone";
  return "failed";
}

/** Why the compare page cannot show the proposals asked for (`shortlist.compare.refusal.*`). */
export type CompareProblem = "count" | "notShortlisted";

export function compareProblem(body: unknown): CompareProblem {
  return apiErrorCode(body) === "not_shortlisted" ? "notShortlisted" : "count";
}
