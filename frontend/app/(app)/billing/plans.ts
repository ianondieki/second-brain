import type { components } from "@/lib/api/schema";
import type { Me } from "@/lib/auth/routing";
import { isOrgId } from "@/lib/billing/upgrade";

// What the Plan & billing screens show (REQ-BIL-08; docs/spec/05): whose plan it is, each plan's price and its
// entitlements in plain words. Prices, names and limits come from GET /api/plans (backend/config/plans.yaml); nothing
// here hard-codes a price or a limit.

export type Plan = components["schemas"]["PlanOut"];
export type Plans = components["schemas"]["PlansOut"];
export type PlanSide = components["schemas"]["PlanSide"];
type Membership = Me["memberships"][number];

/** Who pays for an organisation's plan (the payments policies of revision 0005; docs/spec/03 roles). */
export const PAYING_ROLES: ReadonlySet<string> = new Set(["owner", "admin", "finance"]);

export function pays(membership: Pick<Membership, "roles">): boolean {
  return membership.roles.some((role) => PAYING_ROLES.has(role));
}

/**
 * Whose plan the screen shows. `?org=` names an organisation the person pays for (else it says why not); without it
 * a developer sees their own plan and an organisation member the first organisation they pay for.
 */
export type Subject =
  | { kind: "developer" }
  | { kind: "org"; membership: Membership }
  | { kind: "notPayer"; membership: Membership }
  | { kind: "notMember" }
  | { kind: "noOrg" };

export function billingSubject(me: Pick<Me, "side" | "memberships">, org: string | string[] | undefined): Subject {
  const requested = Array.isArray(org) ? org[0] : org;
  if (requested !== undefined && requested !== "") {
    const found = isOrgId(requested)
      ? me.memberships.find((m) => m.org_id.toLowerCase() === requested.toLowerCase())
      : undefined;
    if (!found) return { kind: "notMember" };
    return pays(found) ? { kind: "org", membership: found } : { kind: "notPayer", membership: found };
  }
  if (me.side !== "org") return { kind: "developer" };
  const paying = me.memberships.find(pays);
  if (paying) return { kind: "org", membership: paying };
  return me.memberships[0] ? { kind: "notPayer", membership: me.memberships[0] } : { kind: "noOrg" };
}

export function sideOf(subject: Extract<Subject, { kind: "developer" | "org" }>): PlanSide {
  return subject.kind === "org" ? "org" : "developer";
}

/** "1,250,000" (or "1,250.50" when there are cents) for an amount in KES minor units; the message adds "KES". */
export function formatKes(minor: number, locale: string): string {
  const whole = minor % 100 === 0;
  return new Intl.NumberFormat(locale === "sw" ? "sw-KE" : "en-KE", {
    minimumFractionDigits: whole ? 0 : 2,
    maximumFractionDigits: whole ? 0 : 2,
  }).format(minor / 100);
}

/** Which price message a plan takes: free, per month, per year, a one-off amount, or not sold here. */
export type PriceKind = "free" | "perMonth" | "perYear" | "once" | "notSold";

export function priceKind(plan: Pick<Plan, "is_default" | "purchasable" | "interval" | "price_kes_minor">): PriceKind {
  if (plan.is_default && plan.price_kes_minor === 0) return "free";
  if (!plan.purchasable) return "notSold"; // custom, approval and eligibility plans (price 0 in plans.yaml)
  if (plan.interval === "month") return "perMonth";
  if (plan.interval === "year") return "perYear";
  return "once";
}

/** One entitlement line: a `billing.line.*` key and its count when it has one. */
export interface Line {
  key:
    | "activeProposals"
    | "activeProposalsUnlimited"
    | "tagsPerProposal"
    | "followedNiches"
    | "recommendations"
    | "viewerAnalytics"
    | "seats"
    | "seatsUnlimited"
    | "scoutAgents"
    | "unlocks"
    | "unlocksUnlimited"
    | "briefs"
    | "briefsUnlimited"
    | "csvExport";
  count?: number;
}

type Limits = Record<string, unknown>;

function count(limits: Limits, key: string): number | null | undefined {
  const value = limits[key];
  if (value === null) return null; // unlimited
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : undefined;
}

/** A capped count: its line, the unlimited line for null, nothing when the plan does not say. */
function capped(limits: Limits, key: string, line: Line["key"], unlimited?: Line["key"]): Line[] {
  const value = count(limits, key);
  if (value === undefined) return [];
  if (value === null) return unlimited ? [{ key: unlimited }] : [];
  return [{ key: line, count: value }];
}

/** A feature only an explicit `true` grants (strings such as "release-2" or "coming-soon" do not; entitlements.py). */
function feature(limits: Limits, key: string, line: Line["key"]): Line[] {
  return limits[key] === true ? [{ key: line }] : [];
}

/**
 * The entitlements worth reading when choosing a plan, in plain words and at most six lines. The rest of plans.yaml
 * (digests, the tracker, the LLM cap) is the same on every plan of a side or not a reason to choose one.
 */
export function planLines(plan: Pick<Plan, "side" | "limits">): Line[] {
  const limits = plan.limits as Limits;
  if (plan.side === "developer") {
    return [
      ...capped(limits, "active_proposals", "activeProposals", "activeProposalsUnlimited"),
      ...capped(limits, "tags_per_proposal", "tagsPerProposal"),
      ...capped(limits, "followed_niches", "followedNiches"),
      ...feature(limits, "recommendations_with_explanations", "recommendations"),
      ...feature(limits, "viewer_analytics", "viewerAnalytics"),
    ];
  }
  return [
    ...capped(limits, "seats", "seats", "seatsUnlimited"),
    ...capped(limits, "scout_agents", "scoutAgents"),
    ...capped(limits, "full_unlocks_per_month", "unlocks", "unlocksUnlimited"),
    ...capped(limits, "problem_briefs", "briefs", "briefsUnlimited"),
    ...feature(limits, "csv_export", "csvExport"),
  ];
}

/**
 * The action a plan's row offers: the primary "Upgrade to" on the plan a 402 would point to (the current plan's
 * `upgrade_to`, when it can be bought here), "Choose" on other plans further up the ladder that can be bought, and
 * nothing on the current plan, plans below it (a downgrade rule is REQ-BIL-06's) or plans not sold here.
 */
export type RowAction = "current" | "upgrade" | "choose" | null;

export function rowAction(plans: readonly Plan[], currentCode: string, plan: Plan): RowAction {
  if (plan.code === currentCode) return "current";
  const current = plans.findIndex((p) => p.code === currentCode);
  const index = plans.findIndex((p) => p.code === plan.code);
  if (!plan.purchasable || index <= current) return null;
  const next = current >= 0 ? plans[current].upgrade_to : null;
  return plan.code === next ? "upgrade" : "choose";
}
