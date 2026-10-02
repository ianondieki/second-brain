import type { ChipKind } from "@/components/tracker/model";
import type { components } from "@/lib/api/schema";

import type { Brief } from "./brief-draft";
import { orgQuery, type Membership } from "./membership";

// The organisation's Problems section (REQ-DIR-05; docs/spec/07 item 1 "Problems (Problem Briefs)"): links, who posts,
// the state each Brief shows and the figures Home counts. The form's own part (draft, checks, body, refusals) is
// brief-draft.ts, re-exported here; the form's browser code imports that module alone (docs/spec/07 item 5).
export * from "./brief-draft";

export type BriefList = components["schemas"]["BriefList"];
export type BriefState = Brief["state"];

export const PROBLEMS_PATH = "/org/problems";

/** The organisation's Briefs; `cursor` a later page, `posted` the note after a new Brief. */
export function problemsHref(
  memberships: readonly Membership[],
  orgId: string,
  { cursor, posted = false }: { cursor?: string; posted?: boolean } = {},
): string {
  return `${PROBLEMS_PATH}${orgQuery(memberships, orgId, { cursor, posted: posted ? "1" : undefined })}`;
}

/** One Brief's page for the chosen organisation. */
export function briefHref(memberships: readonly Membership[], orgId: string, briefId: string): string {
  return `${PROBLEMS_PATH}/${encodeURIComponent(briefId)}${orgQuery(memberships, orgId)}`;
}

/** The "Post a brief" form for the chosen organisation. */
export function newBriefHref(memberships: readonly Membership[], orgId: string): string {
  return `${PROBLEMS_PATH}/new${orgQuery(memberships, orgId)}`;
}

/**
 * Owners, admins, signatories and reviewers post and close Briefs (the API's editor set, revision 0002's
 * _ORG_EDITOR); every member reads them. The API answers 403 to anyone else; this only decides what is offered.
 */
export function postsBriefs(membership: Membership): boolean {
  return membership.roles.some((role) => role === "owner" || role === "admin" || role === "signatory" || role === "reviewer");
}

/**
 * A Brief's state as a mark and words (docs/spec/07 item 6): waiting for staff (a hollow ring), on Discover (a tick),
 * not approved (a warning), closed (a cross). The accent stays for "act here" (p18-design-system.md).
 */
export const STATE_CHIP: Record<BriefState, ChipKind> = {
  in_review: "pending",
  published: "completed",
  rejected: "overdue",
  closed: "ended",
};

export const BRIEF_STATES = ["in_review", "published", "rejected", "closed"] as const satisfies readonly BriefState[];

/** Whether a Brief can still be closed (a closed one cannot; a rejected one leaves nothing to close). */
export function closable(brief: Pick<Brief, "state">): boolean {
  return brief.state === "in_review" || brief.state === "published";
}

export interface BriefStats {
  /** Open Briefs as the plan counts them (not closed, not rejected). */
  open: number;
  /** Of the Briefs read, those waiting for staff. */
  inReview: number;
  /** Published proposals answering the open Briefs read. */
  proposals: number;
}

/** Home's "Problem Briefs" tile from the first page of the list (the plan's own count for "open"). */
export function briefStats(list: Pick<BriefList, "items" | "plan">): BriefStats {
  const open = list.items.filter(closable);
  return {
    open: list.plan.used,
    inReview: open.filter((brief) => brief.state === "in_review").length,
    proposals: open.reduce((sum, brief) => sum + brief.proposal_count, 0),
  };
}

/** True when the plan has no room for another open Brief. */
export function planFull(plan: { problem_briefs: number | null; used: number }): boolean {
  return plan.problem_briefs !== null && plan.used >= plan.problem_briefs;
}

export interface PlanOption {
  code: string;
  name: string;
  purchasable: boolean;
  upgrade_to: string | null;
  limits: Record<string, unknown>;
}

function briefLimit(plan: PlanOption): number | null | undefined {
  const value = plan.limits.problem_briefs;
  return value === null ? null : typeof value === "number" ? value : undefined;
}

/**
 * The plan to buy for more open Briefs: up the current plan's upgrade ladder, the first plan a checkout sells whose
 * open Briefs are unlimited or more than now; else null (the top of the ladder).
 */
export function briefUpgrade(plans: readonly PlanOption[], current: string): PlanOption | null {
  const byCode = new Map(plans.map((p) => [p.code, p]));
  const now = byCode.get(current);
  const have = now ? briefLimit(now) : undefined;
  const more = (p: PlanOption) => {
    const limit = briefLimit(p);
    return p.purchasable && limit !== undefined && (limit === null || (typeof have === "number" && limit > have));
  };
  const seen = new Set<string>();
  for (let code = now?.upgrade_to; code && !seen.has(code); code = byCode.get(code)?.upgrade_to) {
    seen.add(code);
    const plan = byCode.get(code);
    if (plan && more(plan)) return plan;
  }
  return null;
}
