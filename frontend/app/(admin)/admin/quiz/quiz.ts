import { apiErrorCode } from "@/lib/api/error-code";
import type { components } from "@/lib/api/schema";

// The staff quiz screens' pure parts (REQ-DEV-01; D-59; bridge/admin quiz routes): the queue's order, the stats in
// words and which fixed sentence a refusal gets. The API's message text is never shown.

type Schemas = components["schemas"];
export type QuizSetSummary = Schemas["QuizSetSummaryOut"];
export type QuizSetDetail = Schemas["QuizSetDetailOut"];
export type QuizAdminQuestion = Schemas["QuizAdminQuestionOut"];

export const ADMIN_QUIZ_PATH = "/admin/quiz";
/** The longest pull reason staff keep (the API collapses whitespace, then keeps at most 300 characters). */
export const MAX_REASON = 300;

export function setHref(id: string): string {
  return `${ADMIN_QUIZ_PATH}/${encodeURIComponent(id)}`;
}

/** The queue: sets waiting for review, oldest day first (today's before tomorrow's), then decided ones, newest first. */
export function queue(items: readonly QuizSetSummary[]): { waiting: QuizSetSummary[]; decided: QuizSetSummary[] } {
  const byDay = (a: QuizSetSummary, b: QuizSetSummary) => a.quiz_date.localeCompare(b.quiz_date);
  return {
    waiting: items.filter((s) => s.status === "draft").sort(byDay),
    decided: items.filter((s) => s.status !== "draft").sort((a, b) => byDay(b, a)),
  };
}

/** The average score as the page writes it ("3.67"), or null below three plays (the API sends none then). */
export function averageScore(locale: string, value: string | null | undefined): string | null {
  if (value === null || value === undefined) return null;
  const number = Number(value);
  if (!Number.isFinite(number)) return null;
  return new Intl.NumberFormat(`${locale}-KE`, { maximumFractionDigits: 2 }).format(number);
}

/** A flag reason the page names (the API's codes); anything else is "other". */
export const FLAG_REASONS = ["wrong_answer", "unclear", "outdated", "other"] as const;
export type FlagReasonCode = (typeof FLAG_REASONS)[number];
export function flagReason(code: string): FlagReasonCode {
  return (FLAG_REASONS as readonly string[]).includes(code) ? (code as FlagReasonCode) : "other";
}

/** Why a question is pulled, in words: three flags (the API's code), else the staff member's reason as written. */
export function pulledBecause(question: Pick<QuizAdminQuestion, "status" | "pulled_reason">): { byFlags: true } | { reason: string } | null {
  if (question.status !== "pulled") return null;
  if (question.pulled_reason === "three_flags") return { byFlags: true };
  return { reason: question.pulled_reason ?? "" };
}

const REFUSALS = [
  "already_decided",
  "incomplete_set",
  "day_over",
  "already_pulled",
  "already_live",
  "not_found",
  "forbidden",
] as const;
export type RefusalCode = (typeof REFUSALS)[number] | "generic";
export type Refusal = { kind: "stepUp" } | { kind: "refusal"; code: RefusalCode };

/** The refusal for an answer's status and error body (a 404 is "not_found"; a thrown call is "generic"). */
export function refusalOf(status: number, error: unknown): Refusal {
  if (status === 404) return { kind: "refusal", code: "not_found" };
  const code = apiErrorCode(error);
  if (code === "step_up_required") return { kind: "stepUp" };
  if (status === 403) return { kind: "refusal", code: "forbidden" };
  if (code && (REFUSALS as readonly string[]).includes(code)) return { kind: "refusal", code: code as RefusalCode };
  return { kind: "refusal", code: "generic" };
}

/**
 * What a refused decision leaves: a day that is over (or a set without five live questions) can only be rejected, so
 * Reject becomes the one primary action and Approve stays but is inert; a set already decided or gone leaves only the
 * fresh page; anything else can be tried again.
 */
export function refusalNext(code: RefusalCode): "reject" | "reload" | "retry" {
  if (code === "day_over" || code === "incomplete_set") return "reject";
  if (code === "already_decided" || code === "not_found" || code === "already_pulled" || code === "already_live") return "reload";
  return "retry";
}
