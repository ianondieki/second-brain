import type { components } from "@/lib/api/schema";

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
 * day it was published, as the API computes it.
 */
export function problemLabel(
  problem: Pick<ProblemDetail, "source" | "seeded_example" | "published_at">,
  locale: string,
): ProblemLabel {
  if (problem.source === "developer") return { key: "developer" };
  if (problem.source !== "research_agent" || !problem.published_at) return null;
  return { key: problem.seeded_example ? "seeded" : "aiDrafted", date: formatLongDay(locale, problem.published_at) };
}

/** A moment as its Nairobi day, written out ("30 September 2026"). */
export function formatLongDay(locale: string, iso: string): string {
  return new Intl.DateTimeFormat(`${locale}-KE`, { dateStyle: "long", timeZone: "Africa/Nairobi" }).format(
    new Date(iso),
  );
}

/** A moment in Nairobi, short ("30 Sept 2026, 14:06"). */
export function formatMoment(locale: string, iso: string): string {
  return new Intl.DateTimeFormat(`${locale}-KE`, {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Africa/Nairobi",
  }).format(new Date(iso));
}

const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/;

/** A calendar date ("2026-09-28", no time or zone) as written for the page's language; never shifted a day. */
export function formatDate(locale: string, value: string): string {
  if (!DATE_ONLY.test(value)) return value;
  return new Intl.DateTimeFormat(`${locale}-KE`, { dateStyle: "medium", timeZone: "UTC" }).format(
    new Date(`${value}T00:00:00Z`),
  );
}

/** The API's decimal confidence ("0.720") to two places ("0.72"), or null when there is none or it is not a number. */
export function formatConfidence(locale: string, value: string | null | undefined): string | null {
  if (value === null || value === undefined || value.trim() === "") return null;
  const number = Number(value);
  if (!Number.isFinite(number)) return null;
  return new Intl.NumberFormat(`${locale}-KE`, { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(number);
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
