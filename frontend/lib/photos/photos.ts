import index from "@/public/photos/index.json";

// The photographs (D-66): licensed Kenyan photographs from Wikimedia Commons vendored under public/photos (AVIF and
// WebP at 800 and 1600 px), described by public/photos/index.json (with each one's title, author, licence and source,
// from public/photos/CREDITS.md) and credited on /credits. Counties are keyed by their reference code (KE-30), the
// code the API gives: their names differ ("Nairobi City" in the reference data, "Nairobi" on a photograph).

/** One photograph as public/photos/index.json describes it. */
export interface PhotoEntry {
  slug: string;
  /** The place it shows, by its everyday name ("Nairobi"); "Kenya" for a photograph of no one county. */
  county: string;
  /** The county's reference code (KE-30); null for a photograph of no one county. */
  county_code: string | null;
  caption: string;
  width: number;
  height: number;
  /** The work's title on Commons, its author, licence (name and deed) and file page, and what was changed. */
  title: string;
  author: string;
  licence: string;
  licence_url: string;
  source_url: string;
  changes: string;
  /** The one-line attribution. */
  credit: string;
  /** The top-level niche it stands for (P25-A adds one per niche), if any. */
  niche?: string | null;
  /** What it is for (P25-A): "niche", "greeting-morning", "greeting-afternoon", "greeting-evening", "county". */
  role?: string | null;
}

/** A photograph with the folder its files are in. */
export interface Photo extends PhotoEntry {
  dir: string;
}

const ALL: ReadonlyMap<string, Photo> = new Map((index as PhotoEntry[]).map((entry) => [entry.slug, { ...entry, dir: "/photos" }]));

export function photo(slug: string): Photo {
  const found = ALL.get(slug);
  if (!found) throw new Error(`No photograph ${slug} in public/photos/index.json`);
  return found;
}

/** A county of the landing's strip: its reference code, its everyday name and its photograph. */
export interface StripCounty {
  code: string;
  name: string;
  photo: Photo;
}

const strip = (slug: string): StripCounty => {
  const p = photo(slug);
  return { code: p.county_code!, name: p.county, photo: p };
};

/** The six counties of the landing's strip, in order. Explore always shows them, with a count of 0 where it must. */
export const STRIP: readonly StripCounty[] = [
  "nairobi-jacaranda",
  "mombasa-old-town",
  "kisumu-lake-victoria",
  "nakuru-lake",
  "eldoret-town",
  "rongai-market",
].map(strip);

/** Explore's county photographs by code: a second view where a county has one, so the two pages do not repeat. */
const EXPLORE: ReadonlyMap<string, Photo> = new Map(
  [photo("nairobi-golden-hour"), photo("mombasa-likoni-ferry"), ...STRIP.slice(2).map((c) => c.photo)].map((p) => [p.county_code!, p]),
);

/** Tea country (no one county): Explore's "Nationwide" group only. */
export const NATIONWIDE: Photo = photo("kenya-tea");

/** Every vendored photograph, in index order. */
export const ALL_PHOTOS: readonly Photo[] = [...ALL.values()];

/** The signed-out screens' photograph beside the form from 1024 px (AuthShell): signing in, and creating an account. */
export const AUTH_PHOTOS = { signIn: photo("nairobi-jacaranda"), signUp: photo("nairobi-golden-hour") } as const;

/** Every photograph the site shows, credited on /credits: every vendored photograph (the landing's strip, Explore,
 *  the niche bands and Home's greeting draw from the same index), the strip's and Explore's first. */
export const CREDITED: readonly Photo[] = [
  ...new Map([...STRIP.map((c) => c.photo), ...EXPLORE.values(), NATIONWIDE, ...ALL_PHOTOS].map((p) => [p.slug, p])).values(),
];

/** A county's anchor on /explore: its reference code ("KE-30"), the same on the landing's strip. */
export const countyAnchor = (code: string) => code;

/** The photograph of a county on Explore, by its code, if one is vendored (none: the tile is the night band). */
export function photoOf(code: string): Photo | undefined {
  return EXPLORE.get(code);
}
