import type { components } from "@/lib/api/schema";
import { apiErrorCode, detailOf } from "@/lib/api/error-code";

// The research screens' pure parts (REQ-RES-01; docs/spec/06 6.5; PLAN §8 P11): which niches can run, what a run's
// outcome says, and which fixed sentence a refusal gets. The API's message text is never shown: each code (and each
// publish-check reason) has its own sentence under adminResearch.*.

export type Run = components["schemas"]["bridge__admin__research__RunOut"];
export type Candidate = components["schemas"]["CandidateOut"];
export type Sources = components["schemas"]["SourcesOut"];
export type Excerpt = components["schemas"]["ExcerptOut"];
export type AdminNiche = components["schemas"]["AdminNicheOut"];

export interface NicheOption {
  slug: string;
  label: string;
}

/**
 * The niches a run can be started for: those with a saved excerpt for Kenya (POST /runs takes country KE only and
 * refuses a niche without excerpts), named by the taxonomy's label, sorted by it. A niche missing from the taxonomy
 * keeps its slug.
 */
export function runNiches(excerpts: readonly Pick<Excerpt, "niche" | "country">[], niches: readonly AdminNiche[]) {
  const labels = new Map(niches.map((n) => [n.slug, n.label]));
  const slugs = new Set(excerpts.filter((e) => e.country === "KE").map((e) => e.niche));
  return [...slugs]
    .map((slug): NicheOption => ({ slug, label: labels.get(slug) ?? slug }))
    .sort((a, b) => a.label.localeCompare(b.label, "en", { sensitivity: "base" }));
}

/** A niche's label by slug (the taxonomy's), else the slug itself, else null. */
export function nicheLabel(slug: string | null | undefined, niches: readonly AdminNiche[]): string | null {
  if (!slug) return null;
  return niches.find((n) => n.slug === slug)?.label ?? slug;
}

const STOP_REASONS = [
  "stale",
  "no_saved_excerpts",
  "not_enough_excerpts",
  "search_or_fetch_cap",
  "input_token_cap",
  "injection_suspected",
] as const;
type StopReason = (typeof STOP_REASONS)[number];

/** The sentence under a run: its outcome (message key under adminResearch.runs and its values). */
export type RunOutcome =
  | { key: "going" | "failed" | "demoFallback" | "noCard" }
  | { key: "cards"; count: number; total: number }
  | { key: `stop.${StopReason | "other"}` };

export function runOutcome(run: Pick<Run, "status" | "stop_reason" | "demo_fallback" | "candidates" | "discarded">) {
  switch (run.status) {
    case "running":
      return { key: "going" } satisfies RunOutcome;
    case "failed":
      return { key: "failed" } satisfies RunOutcome;
    case "stopped": {
      const reason = (STOP_REASONS as readonly string[]).includes(run.stop_reason ?? "")
        ? (run.stop_reason as StopReason)
        : "other";
      return { key: `stop.${reason}` } satisfies RunOutcome;
    }
    default:
      if (run.demo_fallback) return { key: "demoFallback" } satisfies RunOutcome;
      if (run.candidates === 0) return { key: "noCard" } satisfies RunOutcome;
      return { key: "cards", count: run.candidates, total: run.discarded } satisfies RunOutcome;
  }
}

/** The tracker chip a run's status wears (a mark, a word and a colour; docs/spec/07 item 6). */
export const RUN_CHIP = {
  running: "current",
  completed: "completed",
  stopped: "onHold",
  failed: "overdue",
} as const satisfies Record<Run["status"], string>;

/** Refusals of POST /runs and of POST …/decision, each with its own sentence (adminResearch.refusal.*). */
const REFUSALS = [
  "no_saved_excerpts",
  "unknown_niche",
  "run_in_progress",
  "checklist_required",
  "already_decided",
  "not_found",
  "forbidden",
] as const;
export type RefusalCode = (typeof REFUSALS)[number] | "generic";

/**
 * Why the publish checks refused a card (review.publish_violation, checks.clean_text and checks.rule_violation in
 * the backend). The API names the reason only inside its message ("This card cannot be published: <reason>."), so
 * the reason is read from exactly that shape and matched against this list; anything else is "other". The message
 * itself is never shown.
 */
export const PUBLISH_REASONS = [
  "no_allowlist",
  "no_citation",
  "source_not_saved",
  "sources_archived",
  "control_character",
  "non_latin_text",
  "text_out_of_bounds",
  "unsupported_number",
  "named_org_without_official",
  "needs_official_or_two_publishers",
  "low_confidence",
] as const;
export type PublishReason = (typeof PUBLISH_REASONS)[number] | "other";

const PUBLISH_MESSAGE = /^This card cannot be published: ([a-z_]{1,64})\.$/;

export function publishReason(error: unknown): PublishReason {
  const message = detailOf(error)?.message;
  const found = typeof message === "string" ? PUBLISH_MESSAGE.exec(message) : null;
  const reason = found?.[1];
  return reason && (PUBLISH_REASONS as readonly string[]).includes(reason) ? (reason as PublishReason) : "other";
}

/** What a refused call shows: the step-up form, a publish-check sentence, or a refusal sentence. */
export type Refusal =
  | { kind: "stepUp" }
  | { kind: "publish"; reason: PublishReason }
  | { kind: "refusal"; code: RefusalCode };

/** The refusal for an answer's status and error body (a 404 is always "not_found"; a thrown call is "generic"). */
export function refusalOf(status: number, error: unknown): Refusal {
  if (status === 404) return { kind: "refusal", code: "not_found" };
  const code = apiErrorCode(error);
  if (code === "step_up_required") return { kind: "stepUp" };
  if (code === "publish_check_failed") return { kind: "publish", reason: publishReason(error) };
  if (code && (REFUSALS as readonly string[]).includes(code)) return { kind: "refusal", code: code as RefusalCode };
  return { kind: "refusal", code: "generic" };
}

/** The message key (under adminResearch) of a refusal that is shown as a sentence. */
export function refusalKey(refusal: Exclude<Refusal, { kind: "stepUp" }>): string {
  return refusal.kind === "publish" ? `publish.${refusal.reason}` : `refusal.${refusal.code}`;
}

/** Saved excerpts by niche, in the order of `options` (the runnable niches), newest first within each. */
export function excerptsByNiche(excerpts: readonly Excerpt[], options: readonly NicheOption[]) {
  return options
    .map((option) => ({
      ...option,
      excerpts: excerpts
        .filter((e) => e.niche === option.slug && e.country === "KE")
        .sort((a, b) => b.published_date.localeCompare(a.published_date) || a.id.localeCompare(b.id)),
    }))
    .filter((group) => group.excerpts.length > 0);
}

/** How many of a run's polls to make before telling the admin to refresh later (1.5 s apart: about a minute). */
export const RUN_POLLS = 40;
export const RUN_POLL_MS = 1500;

/** The research page's address, and one candidate's review page. */
export const RESEARCH_PATH = "/admin/research";
export function reviewHref(problemId: string): string {
  return `${RESEARCH_PATH}/candidates/${encodeURIComponent(problemId)}`;
}
