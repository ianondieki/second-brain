import { apiErrorCode, detailOf, isRecord } from "@/lib/api/error-code";
import type { components } from "@/lib/api/schema";
import { upgradePlanOf } from "@/lib/billing/upgrade";
import { NAIROBI } from "@/lib/format";

// The "Post a brief" form's plain logic (REQ-DIR-05; docs/spec/06 6.2 last bullet, 6.5 ProblemCard): its draft and
// checks, the body it sends, and the refusals it words. Apart from briefs.ts (links, states, figures), which re-exports
// it, so the form's page loads only this part in the browser (docs/spec/07 item 5). The API decides; this only words it.

type Schemas = components["schemas"];
export type Brief = Schemas["BriefOut"];
export type BriefBody = Schemas["BriefIn"];
export type BudgetBand = Schemas["BudgetBandOut"];
export type BriefPlan = Schemas["BriefPlanOut"];

/** The ProblemCard's lengths, in characters, as the API checks them (bridge/problems/brief_rules.py MAX_LENGTHS). */
export const BRIEF_LIMITS = { title: 90, statement: 1200, affected: 200 } as const;
/** The statement's words, as the API counts them (docs/spec/06 6.5; bridge/problems/research/checks.py). */
export const MAX_STATEMENT_WORDS = 120;

// ------------------------------------------------------------------------------------------------ the draft

/** What the form holds while it is edited (as typed; empty strings for "none"). */
export interface BriefDraft {
  title: string;
  statement: string;
  affected: string;
  /** A niche id (a parent covers the niches under it). */
  niche: string;
  /** An ISO 3166-2 county code, or "" for anywhere in Kenya. */
  county: string;
  /** A budget band code from the list's budget_bands, or "" for none. */
  band: string;
  /** "YYYY-MM-DD", or "" for no deadline. */
  deadline: string;
}

export const EMPTY_DRAFT: BriefDraft = {
  title: "",
  statement: "",
  affected: "",
  niche: "",
  county: "",
  band: "",
  deadline: "",
};

/** The form's fields, in the order the page shows them (the first with a problem takes focus). */
export const DRAFT_FIELDS = ["title", "statement", "affected", "niche", "county", "band", "deadline"] as const;
export type DraftField = (typeof DRAFT_FIELDS)[number];

/** Words in a text, as the statement's meter counts them. */
export function wordCount(text: string): number {
  const trimmed = text.trim();
  return trimmed ? trimmed.split(/\s+/u).length : 0;
}

/** Characters as the API counts them (code points, after trimming). */
export function charCount(text: string): number {
  return Array.from(text.trim()).length;
}

/** Today in Nairobi as "YYYY-MM-DD" (the deadline's earliest day, as the API decides it). */
export function todayInNairobi(now: Date = new Date()): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: NAIROBI, year: "numeric", month: "2-digit", day: "2-digit" }).format(now);
}

const DAY = /^\d{4}-\d{2}-\d{2}$/;

/** A field's problem, worded under `briefForm.error.*` (the length ones with their limit). */
export type DraftProblem =
  | "titleRequired"
  | "statementRequired"
  | "nicheRequired"
  | "tooLong"
  | "tooManyWords"
  | "deadlinePast"
  | "deadlineInvalid";
export type DraftErrors = Partial<Record<DraftField, DraftProblem>>;

/** What must be fixed before the form is sent (the API checks everything again, contact details included). */
export function checkBrief(draft: BriefDraft, today: string): DraftErrors {
  const errors: DraftErrors = {};
  if (!draft.title.trim()) errors.title = "titleRequired";
  else if (charCount(draft.title) > BRIEF_LIMITS.title) errors.title = "tooLong";
  if (!draft.statement.trim()) errors.statement = "statementRequired";
  else if (charCount(draft.statement) > BRIEF_LIMITS.statement) errors.statement = "tooLong";
  else if (wordCount(draft.statement) > MAX_STATEMENT_WORDS) errors.statement = "tooManyWords";
  if (charCount(draft.affected) > BRIEF_LIMITS.affected) errors.affected = "tooLong";
  if (!draft.niche) errors.niche = "nicheRequired";
  if (draft.deadline) {
    if (!DAY.test(draft.deadline)) errors.deadline = "deadlineInvalid";
    else if (draft.deadline < today) errors.deadline = "deadlinePast";
  }
  return errors;
}

/** The API's BriefIn: public only (invited Briefs come later), blank optional fields as null. */
export function bodyOf(draft: BriefDraft): BriefBody {
  const affected = draft.affected.trim();
  return {
    title: draft.title.trim(),
    statement: draft.statement.trim(),
    affected_group: affected || null,
    niche_id: draft.niche,
    county_code: draft.county || null,
    budget_band: draft.band || null,
    deadline: draft.deadline || null,
    visibility: "public",
  };
}

// ------------------------------------------------------------------------------------------------ refusals

/** Why a Brief was not posted or closed (`briefForm.refusal.*`). */
export type BriefRefusal =
  | "planLimit"
  | "dailyLimit"
  | "verification"
  | "orgUnavailable"
  | "notPublished"
  | "frozen"
  | "forbidden"
  | "visibility"
  | "invalid"
  | "closed"
  | "notFound"
  | "mfaSetup"
  | "mfaCode"
  | "network"
  | "generic";

/** The API's field codes the form words (`briefForm.fieldError.*`); anything else reads "other". */
export const FIELD_CODES = [
  "blank",
  "too_long",
  "contains_url",
  "contains_domain",
  "contains_email",
  "contains_phone",
  "contains_payment_number",
  "unknown_niche",
  "unknown_county",
  "unknown_budget_band",
  "deadline_past",
] as const;
export type FieldCode = (typeof FIELD_CODES)[number] | "other";

/** One field the API refused, by the form's name for it. */
export interface FieldIssue {
  field: DraftField;
  code: FieldCode;
}

const API_FIELDS: Record<string, DraftField> = {
  title: "title",
  statement: "statement",
  affected_group: "affected",
  niche_id: "niche",
  county_code: "county",
  budget_band: "band",
  deadline: "deadline",
};

const CODES: Record<string, BriefRefusal> = {
  verification_required: "verification",
  visibility_not_available: "visibility",
  invalid_brief: "invalid",
  brief_closed: "closed",
  brief_not_published: "notPublished",
  brief_frozen: "frozen",
  briefs_daily_limit: "dailyLimit",
  org_unavailable: "orgUnavailable",
  mfa_enrolment_required: "mfaSetup",
  mfa_required: "mfaCode",
};

export interface Refused {
  ok: false;
  refusal: BriefRefusal;
  /** The next plan up a 402 names (its code; the link is built from it alone), else null. */
  upgradePlan: string | null;
  /** The plan's open Briefs a 402 reports, else null. */
  limit: number | null;
  /** A 422 invalid_brief's fields, each with its code (never the refused text). */
  fields: FieldIssue[];
}

function fieldIssues(error: unknown): FieldIssue[] {
  const list = detailOf(error)?.errors;
  if (!Array.isArray(list)) return [];
  const out: FieldIssue[] = [];
  for (const item of list) {
    if (!isRecord(item) || typeof item.field !== "string" || typeof item.code !== "string") continue;
    const field = API_FIELDS[item.field];
    if (!field || out.some((issue) => issue.field === field)) continue;
    const code = (FIELD_CODES as readonly string[]).includes(item.code) ? (item.code as FieldCode) : "other";
    out.push({ field, code });
  }
  return out;
}

/** The refusal of a Briefs call: a 402 with the next plan up, a 422 with its fields, the rest by code or status. */
export function briefRefusalOf(status: number, error: unknown): Refused {
  const base = { ok: false as const, upgradePlan: null, limit: null, fields: [] };
  if (status === 402) {
    const limit = detailOf(error)?.limit;
    return { ...base, refusal: "planLimit", upgradePlan: upgradePlanOf(error), limit: typeof limit === "number" ? limit : null };
  }
  const code = apiErrorCode(error);
  if (code && code in CODES) {
    const refusal = CODES[code];
    return { ...base, refusal, fields: refusal === "invalid" ? fieldIssues(error) : [] };
  }
  const refusal: BriefRefusal =
    status === 404 ? "notFound" : status === 403 ? "forbidden" : status === 409 ? "closed" : status === 422 || status === 400 ? "invalid" : "generic";
  return { ...base, refusal };
}

export const NETWORK: Refused = { ok: false, refusal: "network", upgradePlan: null, limit: null, fields: [] };
