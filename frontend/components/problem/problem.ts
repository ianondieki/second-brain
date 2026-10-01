import type { components } from "@/lib/api/schema";
import { formatCalendarDate, formatDay, formatMoment } from "@/lib/format";

// The problem card's pure parts (REQ-RES-02; docs/spec/06 6.5): its label, dates, confidence and the one kind of
// link it may carry. Shared by the signed-in problem page and the staff review screen (REQ-RES-01).

export type ProblemDetail = components["schemas"]["ProblemDetail"];
/** A cited source as either API sends it (the public citation or the staff view of a candidate's source). */
export type Citation = Pick<
  components["schemas"]["CitationOut"],
  "url" | "publisher" | "source_type" | "published_date" | "quote"
>;

export type ProblemLabel = { key: "aiDrafted" | "seeded"; date: string } | { key: "developer" } | null;

/**
 * The card's label, in the page's language (the API also sends it in English as `label`): a published research
 * card is "AI-drafted, human-reviewed on <date>", or a seeded example when the demo seed made it (never presented as
 * a live AI result); a developer's problem is "Developer-reported"; anything else has none. `date` is the Nairobi
 * day it was published ("30 Sep 2026"), as the API computes it.
 */
export function problemLabel(
  problem: Pick<ProblemDetail, "source" | "seeded_example" | "published_at">,
  locale: string,
): ProblemLabel {
  if (problem.source === "developer") return { key: "developer" };
  if (problem.source !== "research_agent" || !problem.published_at) return null;
  return { key: problem.seeded_example ? "seeded" : "aiDrafted", date: formatDay(locale, problem.published_at) };
}

/** A problem as Discover and Home receive it: the English `label`, and (from P16-C1) what the label is made of. */
export type ListedProblem = Pick<ProblemDetail, "source" | "label"> & {
  seeded_example?: boolean;
  published_at?: string | null;
};

/**
 * Discover's and Home's label (REQ-TREND-02, REQ-PERS-01): the problem page's own label in the page's language and
 * date format (problemLabel), so one problem reads the same on every screen. An API older than P16-C1 sends no
 * `seeded_example`; then its English words are shown as they are rather than guessing whether the card is a seeded
 * example. When the API sends no label (a research card that is not published, archived for example), none is built
 * here either: the API decides whether a problem is labelled, the page only words it.
 */
export function listedProblemLabel(problem: ListedProblem, locale: string): ProblemLabel | { key: "api"; text: string } {
  if (!problem.label) return null;
  if (problem.source === "developer") return { key: "developer" };
  if (typeof problem.seeded_example === "boolean" && problem.published_at !== undefined) {
    const label = problemLabel({ ...problem, seeded_example: problem.seeded_example, published_at: problem.published_at }, locale);
    if (label) return label;
  }
  return { key: "api", text: problem.label };
}

/** A moment in Nairobi ("30 Sep 2026, 14:06"), the web app's one date format (lib/format.ts). */
export { formatMoment };

/** A calendar date ("2026-09-28", no time or zone) as "28 Sep 2026"; never shifted a day; anything else as it is. */
export function formatDate(locale: string, value: string): string {
  return formatCalendarDate(locale, value);
}

/** The API's decimal confidence ("0.720") to two places ("0.72"), or null when there is none or it is not a number. */
export function formatConfidence(locale: string, value: string | null | undefined): string | null {
  if (value === null || value === undefined || value.trim() === "") return null;
  const number = Number(value);
  if (!Number.isFinite(number)) return null;
  return new Intl.NumberFormat(`${locale}-KE`, { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(number);
}

export type ConfidenceBand = "high" | "medium" | "low";

/** The card's confidence in words (≥ 0.8 high, ≥ 0.5 medium, else low) with the figure as a percentage, for people. */
export function confidenceWords(locale: string, value: string | null | undefined): { band: ConfidenceBand; percent: string } | null {
  if (value === null || value === undefined || value.trim() === "") return null;
  const number = Number(value);
  if (!Number.isFinite(number)) return null;
  const band: ConfidenceBand = number >= 0.8 ? "high" : number >= 0.5 ? "medium" : "low";
  return { band, percent: new Intl.NumberFormat(`${locale}-KE`, { style: "percent", maximumFractionDigits: 0 }).format(number) };
}

/**
 * A source's address when it is a plain https URL, else null (then no link is drawn). The API only stores https URLs
 * on its allowlist; this keeps any other scheme (javascript:, data:) from ever becoming a link.
 */
export function safeHttpsUrl(url: string): string | null {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" && !parsed.username && !parsed.password ? parsed.href : null;
  } catch {
    return null;
  }
}

/** The source types the card names in words (docs/spec/06 6.5 quality tiers, plus a verified organisation's brief). */
const SOURCE_TYPES = ["official", "filing", "news", "ngo", "blog", "social", "verified_org"] as const;
export type SourceType = (typeof SOURCE_TYPES)[number] | "other";

export function sourceType(value: string | null | undefined): SourceType {
  return (SOURCE_TYPES as readonly string[]).includes(value ?? "") ? (value as SourceType) : "other";
}

/** The problem page's address (P12-F links here from Discover). */
export function problemHref(problemId: string): string {
  return `/problems/${encodeURIComponent(problemId)}`;
}
