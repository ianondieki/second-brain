import type { components } from "@/lib/api/schema";
import { apiErrorCode } from "@/lib/api/error-code";

// The moderation screens' pure parts (REQ-MOD-01, REQ-ADM-01; docs/spec/06 6.12; PLAN §8 P15): which view a query
// asks for, what a case is about, which fixed sentence each reason, field, block and refusal gets, and what a moderator
// can still do. The API's own words (its messages) are never shown: every code has a sentence under adminModeration.*.

export type Case = components["schemas"]["CaseOut"];
export type DecisionOut = components["schemas"]["bridge__admin__moderation__DecisionOut"];
export type Choice = Case["actions"][number];
export type Blocked = NonNullable<Case["blocked"]>;

export const MODERATION_PATH = "/admin/moderation";

/** The queue's two views: the unresolved cases (oldest first) and the decided ones (newest decision first). */
export type ModerationView = "open" | "decided";

/** `?view=decided` opens the decided cases; anything else the open ones. */
export function moderationView(value: string | undefined): ModerationView {
  return value === "decided" ? "decided" : "open";
}

export function viewHref(view: ModerationView): string {
  return view === "decided" ? `${MODERATION_PATH}?view=decided` : MODERATION_PATH;
}

export function caseHref(caseId: string): string {
  return `${MODERATION_PATH}/cases/${encodeURIComponent(caseId)}`;
}

/** What a case is about: the two subjects this queue decides, a claim dispute (decided from its own queue), or other. */
export type CaseKind = "proposal" | "problem" | "org_claim" | "other";

export function caseKind(subjectType: string): CaseKind {
  return subjectType === "proposal" || subjectType === "problem" || subjectType === "org_claim" ? subjectType : "other";
}

/** The subject's title as it is now (its Tier-1 title field, else the preview's), or null when it has none. */
export function caseTitle(item: Pick<Case, "fields" | "preview">): string | null {
  const field = item.fields.find((f) => f.name === "title")?.text.trim();
  return field || item.preview.title?.trim() || null;
}

/**
 * Why the pre-screen or a person filed the case. The rules pre-screen (bridge/proposals/prescreen.py) and the publish
 * path (bridge/proposals/service.py) file the first four; the rest are the Haiku pre-screen's classes (docs/spec/06
 * 6.12) for when it is plugged in. Anything else reads "other".
 */
export const REASONS = [
  "names_real_org_negative",
  "security_vulnerability",
  "new_developer_problem",
  "new_version_of_moderated_proposal",
  "spam",
  "defamation",
  "false_affiliation",
  "third_party_personal_data",
  "malicious_links",
] as const;
export type Reason = (typeof REASONS)[number] | "other";

/** A case's reasons as message keys, in the API's order, each once ("other" once for all unknown ones). */
export function caseReasons(reasons: readonly string[]): Reason[] {
  const keys = reasons.map((r) => ((REASONS as readonly string[]).includes(r) ? (r as Reason) : "other"));
  return [...new Set(keys)];
}

/**
 * Routine reasons (every developer problem is queued; a new version of a checked proposal is filed again) read as
 * information; the rest are flags and read as warnings. Both carry a mark and words.
 */
const ROUTINE: readonly Reason[] = ["new_developer_problem", "new_version_of_moderated_proposal"];

export function reasonTone(reason: Reason): "info" | "flag" {
  return ROUTINE.includes(reason) ? "info" : "flag";
}

/** The Tier-1 fields the queue shows (bridge/admin/moderation.py TIER1_FIELDS); anything else is "other". */
export const FIELDS = ["title", "problem_statement", "impact_claims", "summary", "statement"] as const;
export type FieldName = (typeof FIELDS)[number] | "other";

export function fieldKey(name: string): FieldName {
  return (FIELDS as readonly string[]).includes(name) ? (name as FieldName) : "other";
}

/**
 * Whether the subject can be seen outside the queue now (docs/spec/07 item 6: shown as a mark and words): a held
 * subject is hidden until decided, a clear one is public, a rejected one hidden; "gone" when it no longer exists.
 * Null for subjects decided elsewhere (claim disputes).
 */
export type Visibility = "hidden" | "public" | "rejected" | "gone";

export function visibility(item: Pick<Case, "subject_type" | "subject_state" | "blocked">): Visibility | null {
  const kind = caseKind(item.subject_type);
  if (kind !== "proposal" && kind !== "problem") return null;
  if (item.blocked === "subject_gone" || item.subject_state === null) return "gone";
  if (item.subject_state === "held") return "hidden";
  return item.subject_state === "clear" ? "public" : "rejected";
}

/** The tracker chip each visibility wears (a mark, a word and a colour). */
export const VISIBILITY_CHIP = {
  hidden: "onHold",
  public: "current",
  rejected: "ended",
  gone: "ended",
} as const satisfies Record<Visibility, string>;

/** A decided case's outcome, or null while it is unresolved (open, held or escalated). */
export function outcome(item: Pick<Case, "status">): "approved" | "rejected" | null {
  return item.status === "approved" || item.status === "rejected" ? item.status : null;
}

/** Refusals of POST …/cases/{case_id}/decision, each with its own sentence (adminModeration.refusal.*). */
const REFUSALS = [
  "already_decided",
  "not_found",
  "own_content",
  "subject_gone",
  "cannot_approve_vulnerability",
  "unsupported_subject",
  "forbidden",
] as const;
export type RefusalCode = (typeof REFUSALS)[number] | "generic";

/**
 * What a refused decision shows: the step-up form, the "new version" notice (409 case_changed: the page is fetched
 * again and read anew), or a fixed sentence. A 404 is always "not_found"; a 403 other than the step-up is
 * "forbidden" unless the API names own_content; a thrown call or an unknown code is "generic".
 */
export type Refusal = { kind: "stepUp" } | { kind: "changed" } | { kind: "refusal"; code: RefusalCode };

export function refusalOf(status: number, error: unknown): Refusal {
  if (status === 404) return { kind: "refusal", code: "not_found" };
  const code = apiErrorCode(error);
  if (code === "step_up_required") return { kind: "stepUp" };
  if (code === "case_changed") return { kind: "changed" };
  if (code && (REFUSALS as readonly string[]).includes(code)) return { kind: "refusal", code: code as RefusalCode };
  if (status === 403) return { kind: "refusal", code: "forbidden" };
  return { kind: "refusal", code: "generic" };
}

/**
 * What a refusal leaves the moderator to do: only the way back (the case is decided, gone or not theirs to decide),
 * only Reject (vulnerability content is never made public; REQ-PROP-02), or the same choices again.
 */
export function refusalNext(code: RefusalCode): "back" | "rejectOnly" | null {
  if (code === "cannot_approve_vulnerability") return "rejectOnly";
  return code === "generic" ? null : "back";
}
