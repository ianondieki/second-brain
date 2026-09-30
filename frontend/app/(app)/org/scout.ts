import { apiErrorCode } from "@/lib/api/error-code";
import type { components } from "@/lib/api/schema";
import { upgradePlanOf } from "@/lib/billing/upgrade";

import { INBOX_PATH, orgQuery, type Membership } from "./membership";

// The Scout Agent screens' plain logic (REQ-SCOUT-01..03; docs/spec/06 6.8, docs/spec/07 item 1): links, the form's
// draft and its checks, and the fixed sentences each API refusal maps to. The API decides; these only word it.

type Schemas = components["schemas"];
export type Scout = Schemas["ScoutOut"];
export type ScoutList = Schemas["ScoutList"];
export type ScoutPlan = Schemas["ScoutPlanOut"];
export type ScoutBody = Schemas["ScoutForm"];
export type Frequency = Schemas["ScoutFrequency"];
export type Maturity = Schemas["ProposalMaturity"];
export type Match = Schemas["MatchOut"];
export type MatchDetail = Schemas["MatchDetail"];
export type Preview = Schemas["PreviewOut"];
export type InterestState = Schemas["InterestState"];

export const FREQUENCIES = ["daily", "weekly", "on_new"] as const satisfies readonly Frequency[];
export const MATURITIES = ["idea", "prototype", "mvp", "live"] as const satisfies readonly Maturity[];
export const MAX_NICHES = 5;
export const MAX_KEYWORDS = 20;
export const MAX_KEYWORD_CHARS = 60;

// ------------------------------------------------------------------------------------------------ links

/** The Inbox's "Scout matches" tab (the EM3 digest's "N more in your inbox" link). */
export function matchesHref(memberships: readonly Membership[], orgId: string): string {
  return `${INBOX_PATH}${orgQuery(memberships, orgId, { tab: "matches" })}`;
}

/** One match's page (the EM3 digest's item link: /org/inbox/matches/{id}?org=). */
export function matchHref(memberships: readonly Membership[], orgId: string, matchId: string): string {
  return `${INBOX_PATH}/matches/${encodeURIComponent(matchId)}${orgQuery(memberships, orgId)}`;
}

/** The configure-scout screen: a new scout, or one to change. */
export function scoutHref(memberships: readonly Membership[], orgId: string, scoutId?: string): string {
  const path = scoutId ? `${INBOX_PATH}/scouts/${encodeURIComponent(scoutId)}` : `${INBOX_PATH}/scouts/new`;
  return `${path}${orgQuery(memberships, orgId)}`;
}

/** Owners and admins configure scouts (the API answers 403 to anyone else). */
export function configuresScouts(membership: Membership): boolean {
  return membership.roles.includes("owner") || membership.roles.includes("admin");
}

// ------------------------------------------------------------------------------------------------ the form

/** Keywords typed as one list: commas or new lines between them, spaces collapsed, lower case, no repeats. */
export function parseKeywords(text: string): string[] {
  const out: string[] = [];
  for (const part of text.split(/[,\n]/)) {
    const keyword = part.trim().replace(/\s+/g, " ").toLowerCase();
    if (keyword && !out.includes(keyword)) out.push(keyword);
  }
  return out;
}

/** What the form holds while it is edited (text fields as typed). */
export interface ScoutDraft {
  niches: string[];
  counties: string[];
  include: string;
  exclude: string;
  maturity: Maturity[];
  minFit: string;
  frequency: Frequency;
  language: "en" | "sw";
  recipients: string[];
}

/** A new scout's starting point (the plan's weekly scout, min_fit 60), or the saved scout's settings. */
export function draftOf(scout: Scout | undefined, plan: ScoutPlan): ScoutDraft {
  if (!scout) {
    const frequency = plan.frequencies.includes("weekly") ? "weekly" : (plan.frequencies[0] ?? "weekly");
    return {
      niches: [],
      counties: [],
      include: "",
      exclude: "",
      maturity: [],
      minFit: "60",
      frequency,
      language: "en",
      recipients: [],
    };
  }
  return {
    niches: scout.niches.map((n) => n.id),
    counties: [...scout.counties],
    include: scout.include_keywords.join(", "),
    exclude: scout.exclude_keywords.join(", "),
    maturity: [...scout.maturity],
    minFit: String(scout.min_fit),
    frequency: scout.frequency,
    language: scout.language === "sw" ? "sw" : "en",
    recipients: [...scout.recipients],
  };
}

export type DraftProblem = "nichesRequired" | "nichesMax" | "tooMany" | "tooLong" | "minFit";
export type DraftErrors = Partial<Record<"niches" | "include" | "exclude" | "minFit", DraftProblem>>;

function keywordProblem(text: string): DraftProblem | undefined {
  const keywords = parseKeywords(text);
  if (keywords.length > MAX_KEYWORDS) return "tooMany";
  if (keywords.some((k) => k.length > MAX_KEYWORD_CHARS)) return "tooLong";
  return undefined;
}

/** What must be fixed before the form is sent (the API checks everything again). */
export function checkDraft(draft: ScoutDraft): DraftErrors {
  const errors: DraftErrors = {};
  if (draft.niches.length === 0) errors.niches = "nichesRequired";
  else if (draft.niches.length > MAX_NICHES) errors.niches = "nichesMax";
  const include = keywordProblem(draft.include);
  if (include) errors.include = include;
  const exclude = keywordProblem(draft.exclude);
  if (exclude) errors.exclude = exclude;
  const fit = draft.minFit.trim();
  if (!/^\d{1,3}$/.test(fit) || Number(fit) > 100) errors.minFit = "minFit";
  return errors;
}

/**
 * The API's ScoutForm (create, Preview; PATCH takes the same fields). The budget band is left out: proposals carry no
 * budget yet (tasks/REQ-SCOUT-02.md deviation 2), so the form does not ask for one and a saved band stays as it is.
 */
export function bodyOf(draft: ScoutDraft): ScoutBody {
  return {
    niches: [...draft.niches],
    counties: [...draft.counties],
    include_keywords: parseKeywords(draft.include),
    exclude_keywords: parseKeywords(draft.exclude),
    maturity: [...draft.maturity],
    min_fit: Number(draft.minFit.trim()),
    frequency: draft.frequency,
    language: draft.language,
    recipients: [...draft.recipients],
  };
}

// ------------------------------------------------------------------------------------------------ refusals

/** Why a scout was not saved, previewed, paused or resumed (`scoutForm.refusal.*`). */
export type ScoutRefusal =
  | "planLimit"
  | "unknownNiche"
  | "unknownCounty"
  | "invalidRecipients"
  | "invalid"
  | "forbidden"
  | "mfaSetup"
  | "mfaCode"
  | "notFound"
  | "network"
  | "generic";

const SCOUT_CODES: Record<string, ScoutRefusal> = {
  unknown_niche: "unknownNiche",
  unknown_county: "unknownCounty",
  invalid_recipients: "invalidRecipients",
  mfa_enrolment_required: "mfaSetup",
  mfa_required: "mfaCode",
};

/** The refusal of a scouts call, with the next plan up for a 402 (the upgrade link is built from its code only). */
export function scoutRefusalOf(status: number, error: unknown): { refusal: ScoutRefusal; upgradePlan: string | null } {
  if (status === 402) return { refusal: "planLimit", upgradePlan: upgradePlanOf(error) };
  const code = apiErrorCode(error);
  const refusal: ScoutRefusal =
    code && code in SCOUT_CODES
      ? SCOUT_CODES[code]
      : status === 404
        ? "notFound"
        : status === 403
          ? "forbidden"
          : status === 422 || status === 400
            ? "invalid"
            : "generic";
  return { refusal, upgradePlan: null };
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

// ------------------------------------------------------------------------------------------------ an edited scout

/** What the form can offer now: active niches (parents and children), the counties, the organisation's reviewers. */
export interface Offered {
  niches: ReadonlySet<string>;
  counties: ReadonlySet<string>;
  recipients: ReadonlySet<string>;
}

/**
 * A saved scout's choices the form no longer offers (a niche made inactive, a reviewer who left or lost the role)
 * are dropped from the draft, so a save never sends them back to a 422. `dropped` says whether the note shows.
 */
export function pruneDraft(draft: ScoutDraft, offered: Offered): { draft: ScoutDraft; dropped: boolean } {
  const niches = draft.niches.filter((id) => offered.niches.has(id));
  const counties = draft.counties.filter((code) => offered.counties.has(code));
  const recipients = draft.recipients.filter((id) => offered.recipients.has(id));
  const dropped =
    niches.length !== draft.niches.length ||
    counties.length !== draft.counties.length ||
    recipients.length !== draft.recipients.length;
  return { draft: { ...draft, niches, counties, recipients }, dropped };
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

// ------------------------------------------------------------------------------------------------ a kept draft

/** Where an unsaved draft waits during the checkout round trip (this tab only), per organisation and scout. */
export function draftKey(orgId: string, scoutId?: string): string {
  return `bridge.scoutDraft:${orgId}:${scoutId ?? "new"}`;
}

const TEXT = (v: unknown): v is string => typeof v === "string" && v.length <= 2000;
const LIST = (v: unknown): v is string[] => Array.isArray(v) && v.length <= 60 && v.every((x) => TEXT(x));

/** A stored draft read back, or null when it is missing or not a draft's shape (never trusted beyond the form). */
export function parseDraft(raw: string | null): ScoutDraft | null {
  if (!raw) return null;
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return null;
  }
  if (typeof value !== "object" || value === null) return null;
  const d = value as Record<string, unknown>;
  if (!LIST(d.niches) || !LIST(d.counties) || !LIST(d.recipients) || !LIST(d.maturity)) return null;
  if (!TEXT(d.include) || !TEXT(d.exclude) || !TEXT(d.minFit)) return null;
  if (!(FREQUENCIES as readonly unknown[]).includes(d.frequency) || (d.language !== "en" && d.language !== "sw")) return null;
  if (!d.maturity.every((m) => (MATURITIES as readonly string[]).includes(m))) return null;
  return {
    niches: d.niches,
    counties: d.counties,
    include: d.include,
    exclude: d.exclude,
    maturity: d.maturity as Maturity[],
    minFit: d.minFit,
    frequency: d.frequency as Frequency,
    language: d.language,
    recipients: d.recipients,
  };
}
