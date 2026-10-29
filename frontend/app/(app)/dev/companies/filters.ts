import type { components } from "@/lib/api/schema";

export type OrgKind = components["schemas"]["OrgKind"];
export type OrgCard = components["schemas"]["OrgCard"];
export type DirectoryPage = components["schemas"]["DirectoryPage"];
export type DirectoryGroup = components["schemas"]["DirectoryGroup"];
export type NicheNode = components["schemas"]["NicheNode"];
export type FilterOptions = components["schemas"]["FilterOptions"];
export type BadgeLevel = components["schemas"]["Badge"]["level"];

/** Every org type, in the order of docs/spec/03 (the API's OrgKind enum; the check below fails tsc if one is missing). */
export const ORG_KINDS = [
  "company",
  "sme",
  "sacco_mfi",
  "university_tvet",
  "school",
  "national_govt",
  "county_govt",
  "ngo_pbo",
  "development_partner",
] as const satisfies readonly OrgKind[];
type MissingKinds = Exclude<OrgKind, (typeof ORG_KINDS)[number]>;
const everyKindListed: [MissingKinds] extends [never] ? true : MissingKinds = true;
void everyKindListed;

export const BASE_PATH = "/dev/companies";
/** Organisations per page: enough to scan, small enough for a phone on mobile data. */
export const PAGE_SIZE = 30;

/** The screen's filters, one value each (the API takes several; the screen offers one select per filter). */
export interface DirectoryFilters {
  q?: string;
  niche?: string;
  kind?: OrgKind;
  county?: string;
  cursor?: string;
}

// The API's own limits (GET /api/directory/orgs): anything outside them is dropped here instead of failing there.
const NICHE_SLUG = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const COUNTY = /^KE-\d{2}$/;
const KINDS: ReadonlySet<string> = new Set(ORG_KINDS);

type SearchParams = Record<string, string | string[] | undefined>;

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

/** The filters in a URL's query, validated; unknown or malformed values are left out. */
export function parseFilters(params: SearchParams): DirectoryFilters {
  const out: DirectoryFilters = {};
  // Postgres text cannot hold NUL; the API refuses it, so it goes here. Whitespace-only searches are no search.
  const q = first(params.q)
    ?.replace(/\u0000/g, "")
    .trim();
  // At most 100 characters (the API's limit), cut by code point: slicing UTF-16 units could split an emoji into a
  // lone surrogate, which encodeURIComponent refuses (URIError) when the query is sent or linked.
  if (q) out.q = Array.from(q).slice(0, 100).join("");
  const niche = first(params.niche);
  if (niche && niche.length <= 80 && NICHE_SLUG.test(niche)) out.niche = niche;
  const kind = first(params.kind);
  if (kind && KINDS.has(kind)) out.kind = kind as OrgKind;
  const county = first(params.county);
  if (county && COUNTY.test(county)) out.county = county;
  const cursor = first(params.cursor);
  if (cursor && cursor.length <= 2000) out.cursor = cursor;
  return out;
}

/** How many of the three select filters are set (the search box is counted apart). */
export function activeFilterCount({ niche, kind, county }: DirectoryFilters): number {
  return [niche, kind, county].filter(Boolean).length;
}

/** True when a search or a filter narrows the list (an empty result then means "no match", not "nothing listed"). */
export function isNarrowed(filters: DirectoryFilters): boolean {
  return Boolean(filters.q) || activeFilterCount(filters) > 0;
}

/** A link to the directory with these filters (and cursor, when given): /dev/companies?q=…&niche=… */
export function filtersHref(filters: DirectoryFilters): string {
  return withQuery(BASE_PATH, filters);
}

/**
 * An organisation's page, carrying the list's search, filters and page (/dev/companies/{id}?county=…), so its
 * "All companies" link returns to the same list rather than the first page of everything.
 */
export function orgHref(orgId: string, filters: DirectoryFilters = {}): string {
  return withQuery(`${BASE_PATH}/${encodeURIComponent(orgId)}`, filters);
}

function withQuery(path: string, { q, niche, kind, county, cursor }: DirectoryFilters): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries({ q, niche, kind, county, cursor })) if (value) query.set(key, value);
  const text = query.toString();
  return text ? `${path}?${text}` : path;
}

/** The query for GET /api/directory/orgs. */
export function browseQuery({ q, niche, kind, county, cursor }: DirectoryFilters) {
  return {
    q,
    niche: niche ? [niche] : undefined,
    kind: kind ? [kind] : undefined,
    county: county ? [county] : undefined,
    cursor,
    limit: PAGE_SIZE,
  };
}

/** A niche heading "ICT › Networks & Telecommunications" as its parent ("ICT") and its own name. */
export function splitNicheLabel(label: string): { parent?: string; name: string } {
  const at = label.lastIndexOf("›");
  if (at < 0) return { name: label.trim() };
  const parent = label.slice(0, at).trim();
  const name = label.slice(at + 1).trim();
  return parent && name ? { parent, name } : { name: label.trim() };
}

/** Number of organisations on a page (an organisation in two niches counts under each heading). */
export function countOrgs(page: DirectoryPage): number {
  return page.groups.reduce((sum, group) => sum + group.orgs.length, 0);
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function isOrgId(value: string): boolean {
  return UUID.test(value);
}
