import { ALL_PHOTOS, photo, type Photo } from "./photos";

// A photograph for a niche or a county (D-67, P25): the narrow band on problem, idea and engagement cards, on problem
// pages and company pages. Decorative: the niche's or the county's name is always shown beside it. A niche at any
// level maps to its top-level niche (backend/seed/reference.yaml's two-level taxonomy); a top-level niche takes the
// photograph public/photos/index.json marks with its `niche` (P25-A: one per top-level niche), else one of P24's that
// fits; anything else gets none (the lattice). The county's own photograph comes first (nichePhoto).

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

/** A county's photograph by its reference code ("KE-30"): the index's `county` role first, else any of that county. */
export function countyPhoto(code: string | null | undefined): Photo | undefined {
  if (!code) return undefined;
  return (
    ALL_PHOTOS.find((p) => p.county_code === code && p.role === "county") ??
    ALL_PHOTOS.find((p) => p.county_code === code)
  );
}

/**
 * Every photograph of a county that shows the place itself (P26): any role but `niche` (a niche's photograph taken
 * there, such as a named campus, stands for the niche, not the county), its `county` role first, then the index's
 * order. Nairobi has four (the jacaranda, the skyline, golden hour, morning); most counties one; many none.
 */
export function countyPhotos(code: string | null | undefined): readonly Photo[] {
  if (!code) return [];
  const own = ALL_PHOTOS.filter((p) => p.county_code === code && p.role !== "niche");
  return [...own.filter((p) => p.role === "county"), ...own.filter((p) => p.role !== "county")];
}

/**
 * The photograph for a problem, an idea or a company: the county's own photograph (the index's `county` role) when the
 * county has one, as the place a problem comes from reads before its sector; else the niche's (any level: its
 * top-level niche's mark in the index, or P24's that fits); with no niche, any photograph of the county; else none
 * (the caller draws the lattice). A niche's photograph taken in some county never stands in for another niche: a
 * Turkana agriculture problem shows the tea, not Turkana's dispensary.
 */
export function nichePhoto({ niche, county }: { niche?: string | null; county?: string | null }): Photo | undefined {
  const place = county ? ALL_PHOTOS.find((p) => p.county_code === county && p.role === "county") : undefined;
  if (place) return place;
  const top = niche ? topNiche(niche) : null;
  if (!top) return countyPhoto(county);
  return ALL_PHOTOS.find((p) => p.niche === top) ?? (INTERIM[top] ? photo(INTERIM[top]) : undefined);
}

/**
 * The photographs an organisation's band may show, in order (P26: the Companies cards and a company page): its HQ
 * county's own (countyPhotos), else its niche's top-level photograph unless that shows a named organisation's premises
 * (`institution`: Strathmore's campus must not stand for another university), else none (the caller draws the lattice).
 */
export function placePhotos({ county, niche }: { county?: string | null; niche?: string | null }): readonly Photo[] {
  const place = countyPhotos(county);
  if (place.length > 0) return place;
  const top = niche ? nichePhoto({ niche }) : undefined;
  return top && !top.institution ? [top] : [];
}
