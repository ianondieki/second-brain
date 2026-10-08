import { ALL_PHOTOS, photo, type Photo } from "./photos";

// A photograph for a niche or a county (D-67, P25): the narrow band on problem, idea and engagement cards, on problem
// pages and company pages. Decorative: the niche's or the county's name is always shown beside it. A niche at any
// level maps to its top-level niche (backend/seed/reference.yaml's two-level taxonomy); a top-level niche takes the
// photograph public/photos/index.json marks with its `niche` (P25-A adds one per niche), else, until then, one of
// P24's that fits; the public sector takes the county's photograph; anything else gets none (the lattice band).

/** Child niche → its top-level niche (backend/seed/reference.yaml). */
const PARENT: Readonly<Record<string, string>> = {
  "microfinance-saccos": "financial-services",
  "networks-telecommunications": "ict",
  "higher-education": "education",
  "basic-education": "education",
  "national-government": "public-sector",
  "county-government": "public-sector",
};

/** Until P25-A's photographs: the three P24 photographs that fit a niche. */
const INTERIM: Readonly<Record<string, string>> = {
  agriculture: "kenya-tea",
  logistics: "mombasa-likoni-ferry",
  retail: "rongai-market",
};

/** A niche's top-level slug ("microfinance-saccos" → "financial-services"; a top level is itself). */
export function topNiche(slug: string): string {
  return PARENT[slug] ?? slug;
}

/** A county's photograph by its reference code ("KE-30"), the first the index lists for it. */
export function countyPhoto(code: string | null | undefined): Photo | undefined {
  if (!code) return undefined;
  return ALL_PHOTOS.find((p) => p.county_code === code);
}

/**
 * The photograph for a niche (any level) and, for the public sector or no niche at all, the county; undefined when
 * there is none (the caller draws the lattice band).
 */
export function nichePhoto({ niche, county }: { niche?: string | null; county?: string | null }): Photo | undefined {
  const top = niche ? topNiche(niche) : null;
  if (top) {
    const marked = ALL_PHOTOS.find((p) => p.niche === top);
    if (marked) return marked;
    if (INTERIM[top]) return photo(INTERIM[top]);
    if (top !== "public-sector") return undefined;
  }
  return countyPhoto(county);
}
