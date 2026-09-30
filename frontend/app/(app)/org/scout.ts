import { apiErrorCode } from "@/lib/api/error-code";
import type { components } from "@/lib/api/schema";

import { INBOX_PATH, orgQuery, type Membership } from "./membership";
import type { Frequency } from "./scout-draft";

// The Scout Agent screens' plain logic (REQ-SCOUT-01..03; docs/spec/06 6.8, docs/spec/07 item 1): links, the form's
// draft and its checks, and the fixed sentences each API refusal maps to. The API decides; these only word it. The
// form's own part (its draft and checks, the body it sends, its refusals, the kept draft) is scout-draft.ts, re-exported
// here; the form's browser code imports that module alone, so the rest stays out of the configure-scout page's JS
// (docs/spec/07 item 5, the 150 KB budget).
export * from "./scout-draft";

type Schemas = components["schemas"];
export type ScoutList = Schemas["ScoutList"];
export type Match = Schemas["MatchOut"];
export type MatchDetail = Schemas["MatchDetail"];
export type InterestState = Schemas["InterestState"];

// ------------------------------------------------------------------------------------------------ links

/** The Inbox's "Scout matches" tab (the EM3 digest's "N more in your inbox" link). */
export function matchesHref(memberships: readonly Membership[], orgId: string): string {
  return `${INBOX_PATH}${orgQuery(memberships, orgId, { tab: "matches" })}`;
}

/** One match's page (the EM3 digest's item link: /org/inbox/matches/{id}?org=). */
export function matchHref(memberships: readonly Membership[], orgId: string, matchId: string): string {
  return `${INBOX_PATH}/matches/${encodeURIComponent(matchId)}${orgQuery(memberships, orgId)}`;
}

/** The configure-scout screen: a new scout, or one to change; `restore` brings a kept draft back (after checkout). */
export function scoutHref(
  memberships: readonly Membership[],
  orgId: string,
  scoutId?: string,
  { restore = false }: { restore?: boolean } = {},
): string {
  const path = scoutId ? `${INBOX_PATH}/scouts/${encodeURIComponent(scoutId)}` : `${INBOX_PATH}/scouts/new`;
  return `${path}${orgQuery(memberships, orgId, { restore: restore ? "1" : undefined })}`;
}

/** Owners and admins configure scouts (the API answers 403 to anyone else). */
export function configuresScouts(membership: Membership): boolean {
  return membership.roles.includes("owner") || membership.roles.includes("admin");
}

// ------------------------------------------------------------------------------------------------ matches

export type WhySource = "model" | "code" | "demoFallback";

/** Who wrote "why this matches": the model, the scout's rules, or the rules because the model was a demo fallback. */
export function whySourceOf(match: Pick<Match, "why_source" | "demo_fallback">): WhySource {
  if (match.demo_fallback) return "demoFallback";
  return match.why_source === "model" ? "model" : "code";
}

export const INTEREST_REASONS = [
  "org_not_e2",
  "org_unavailable",
  "role_required",
  "engagement_exists",
  "proposal_unavailable",
] as const;
export type InterestReason = (typeof INTEREST_REASONS)[number] | "other";

/** Why Express interest is not offered now (`scoutMatch.reason.*`), or null when it is. */
export function interestReasonOf(state: InterestState): InterestReason | null {
  if (state.allowed) return null;
  return (INTEREST_REASONS as readonly string[]).includes(state.reason ?? "")
    ? (state.reason as InterestReason)
    : "other";
}

/** Why Express interest was refused (`expressInterest.refusal.*`); "stepUp" opens the code form instead. */
export type InterestRefusal =
  | "stepUp"
  | "role_required"
  | "org_not_e2"
  | "org_unavailable"
  | "engagement_exists"
  | "proposal_unavailable"
  | "invalidContactBy"
  | "invalidContact"
  | "mfaSetup"
  | "network"
  | "generic";

const INTEREST_CODES: Record<string, InterestRefusal> = {
  step_up_required: "stepUp",
  role_required: "role_required",
  org_not_e2: "org_not_e2",
  org_unavailable: "org_unavailable",
  engagement_exists: "engagement_exists",
  invalid_contact_by: "invalidContactBy",
  invalid_contact: "invalidContact",
  mfa_enrolment_required: "mfaSetup",
};

/**
 * The refusal of POST /api/orgs/{org_id}/interest. A 404 is the one answer for an unavailable proposal, a match that
 * is gone and (by design) a developer who is a member of the organisation: the same sentence for all three.
 */
export function interestRefusalOf(status: number, error: unknown): InterestRefusal {
  const code = apiErrorCode(error);
  if (code && code in INTEREST_CODES) return INTEREST_CODES[code];
  if (status === 404) return "proposal_unavailable";
  return "generic";
}

// ------------------------------------------------------------------------------------------------ plans

export interface PlanOption {
  code: string;
  purchasable: boolean;
  upgrade_to: string | null;
  limits: Record<string, unknown>;
}

function frequenciesOf(plan: PlanOption): readonly string[] {
  const value = plan.limits.scout_frequencies;
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [];
}

/**
 * The plan to buy for a schedule the current plan lacks: up the current plan's upgrade ladder, the first plan that
 * sells it (a checkout can buy it) and includes the frequency; else the first such plan of the side; else null.
 */
export function planFor(plans: readonly PlanOption[], current: string, frequency: Frequency): string | null {
  const byCode = new Map(plans.map((p) => [p.code, p]));
  const fits = (p: PlanOption | undefined) => p !== undefined && p.purchasable && frequenciesOf(p).includes(frequency);
  const seen = new Set<string>();
  for (let code = byCode.get(current)?.upgrade_to; code && !seen.has(code); code = byCode.get(code)?.upgrade_to) {
    seen.add(code);
    if (fits(byCode.get(code))) return code;
  }
  return plans.find((p) => fits(p))?.code ?? null;
}
