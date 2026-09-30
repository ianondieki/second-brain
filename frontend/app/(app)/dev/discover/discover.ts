import type { components } from "@/lib/api/schema";

// Types, addresses and pure helpers of Developer › Discover (REQ-TREND-02; docs/spec/06 6.6, docs/spec/07 items 1-2).
// The types come from the generated schema (backend/openapi.json); nothing here calls the API.

type Schemas = components["schemas"];
export type TrendingOut = Schemas["TrendingOut"];
export type TrendingProblem = Schemas["TrendingProblem"];
export type TrendingProject = Schemas["TrendingProject"];
export type DiscoverProblem = Schemas["DiscoverProblem"];
export type DiscoverSource = Schemas["DiscoverSource"];
export type ProblemRef = Schemas["ProblemRef"];
export type OpportunityGapOut = Schemas["OpportunityGapOut"];
export type NicheNode = Schemas["NicheNode"];
export type CountyRef = Schemas["CountyRef"];

export const DISCOVER_PATH = "/dev/discover";
export const NICHES_PATH = "/dev/discover/niches";
/** The profiling consent's section on the niches page (Home's "Recommended for you" note links here). */
export const PROFILING_HREF = `${NICHES_PATH}#profiling`;

/** Discover's three lists (docs/spec/07 item 1): one at a time, chosen in the address so each is shareable. */
export const VIEWS = ["problems", "projects", "gap"] as const;
export type View = (typeof VIEWS)[number];

/** The API lists at most 20 per list (REQ-TREND-01 card); the screen never shows more. */
export const MAX_ITEMS = 20;

export interface DiscoverQuery {
  view: View;
  /** A niche slug (a parent includes its children). */
  niche?: string;
  /** An ISO 3166-2 county code (KE-01 … KE-47). */
  county?: string;
}

type SearchParams = Record<string, string | string[] | undefined>;

// The API's own shapes: anything else is dropped here instead of failing there.
const NICHE_SLUG = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const COUNTY = /^KE-\d{2}$/;

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

/** The view and filters in a URL's query, validated; unknown or malformed values are left out. */
export function parseDiscover(params: SearchParams): DiscoverQuery {
  const view = first(params.view);
  const out: DiscoverQuery = { view: (VIEWS as readonly string[]).includes(view ?? "") ? (view as View) : "problems" };
  const niche = first(params.niche);
  if (niche && niche.length <= 80 && NICHE_SLUG.test(niche)) out.niche = niche;
  const county = first(params.county);
  if (county && COUNTY.test(county)) out.county = county;
  return out;
}

/** True when a niche or county narrows the lists (an empty list then means "nothing here", not "nothing at all"). */
export function isNarrowed({ niche, county }: DiscoverQuery): boolean {
  return Boolean(niche || county);
}

/** /dev/discover?view=…&niche=…&county=…, leaving out the default view ("problems"). */
export function discoverHref({ view = "problems", niche, county }: Partial<DiscoverQuery> = {}): string {
  const query = new URLSearchParams();
  if (view !== "problems") query.set("view", view);
  if (niche) query.set("niche", niche);
  if (county) query.set("county", county);
  const text = query.toString();
  return text ? `${DISCOVER_PATH}?${text}` : DISCOVER_PATH;
}

/** The query for GET /api/discover/trending and /api/discover/opportunity-gap. */
export function trendQuery({ niche, county }: DiscoverQuery): { niche?: string; county?: string } {
  return { niche, county };
}

/** A new idea that already links this problem (the editor reads `?problem=`). */
export function startProposalHref(problemId: string): string {
  return `/dev/ideas/new?problem=${encodeURIComponent(problemId)}`;
}

/** The id of a project's row on the Projects view, so a problem can link to the project beside it and back. */
export function projectAnchor(proposalId: string): string {
  return `project-${proposalId}`;
}

export function problemAnchor(problemId: string): string {
  return `problem-${problemId}`;
}

/**
 * Chips that say "Trending" only when the item trends (docs/spec/06 6.6: the badge and its words wait for the
 * baseline and 3 distinct actors). The API words them from the same facts; this keeps a card honest if they ever
 * disagree.
 */
export function honestChips(trending: boolean, chips: readonly string[]): string[] {
  return trending ? [...chips] : chips.filter((chip) => !/^trending\b/i.test(chip.trim()));
}

/**
 * The chips a card shows (docs/spec/07 item 2: at most two). A trending card's badge already explains the trend in a
 * sentence, so it keeps one Why chip that the badge does not already say; any other card shows up to two. The rest
 * are listed when the card is expanded.
 */
export function cardChips(trend: { trending: boolean; badge: string | null }, why: readonly string[]): string[] {
  const badge = trend.trending ? (trend.badge ?? "") : "";
  const fresh = honestChips(trend.trending, why).filter((chip) => !badge.includes(chip));
  return fresh.slice(0, badge ? 1 : 2);
}

/** Why chips not shown on the card itself (they go under "More about this problem"). */
export function moreWhy(trend: { trending: boolean; badge: string | null }, why: readonly string[]): string[] {
  const shown = new Set(cardChips(trend, why));
  return honestChips(trend.trending, why).filter((chip) => !shown.has(chip));
}

/**
 * Cold start (docs/spec/06 6.6): until a niche has a baseline and enough distinct actors nothing trends, and the list
 * is what is new this week.
 */
export function isColdStart(items: readonly { trend: { trending: boolean } }[]): boolean {
  return items.length > 0 && items.every((item) => !item.trend.trending);
}

/** The trending projects by proposal id, for the problems they solve. */
export function projectsById(projects: readonly TrendingProject[]): Map<string, TrendingProject> {
  return new Map(projects.map((project) => [project.proposal.id, project]));
}

/** A county code's name from the directory's list, or null (the caller then names the country). */
export function countyName(code: string | null, counties: readonly CountyRef[]): string | null {
  if (!code) return null;
  return counties.find((county) => county.code === code)?.name ?? null;
}

/** "KE" as the reader's language names it ("Kenya"), or the code when the runtime cannot. */
export function countryName(code: string, locale: string): string {
  try {
    return new Intl.DisplayNames([locale], { type: "region" }).of(code) ?? code;
  } catch {
    return code;
  }
}

/** The niche tree flattened for a select or a checklist, parents before their children. */
export interface NicheOption {
  id: string;
  slug: string;
  name: string;
  /** The parent's name for a child niche. */
  parent?: string;
}

export function nicheOptions(tree: readonly NicheNode[]): NicheOption[] {
  return tree.flatMap((parent) => [
    { id: parent.id, slug: parent.slug, name: parent.name },
    ...parent.children.map((child) => ({ id: child.id, slug: child.slug, name: child.name, parent: parent.name })),
  ]);
}
