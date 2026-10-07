import index from "@/public/photos/index.json";

// The photographs (D-66): licensed Kenyan photographs from Wikimedia Commons vendored under public/photos (AVIF and
// WebP at 800 and 1600 px, a 24 px blur), described by public/photos/index.json, with their full record in
// public/photos/CREDITS.md and their attribution lines on /credits.

/** One photograph as public/photos/index.json describes it. */
export interface PhotoEntry {
  slug: string;
  /** The county it shows, by name ("Nairobi", "Uasin Gishu"); "Kenya" for a photograph of no one county. */
  county: string;
  caption: string;
  width: number;
  height: number;
  /** The exact attribution line to show (author, licence, source). */
  credit: string;
}

/** A photograph with the folder its files are in. */
export interface Photo extends PhotoEntry {
  dir: string;
}

const ALL: ReadonlyMap<string, Photo> = new Map((index as PhotoEntry[]).map((entry) => [entry.slug, { ...entry, dir: "/photos" }]));

function photo(slug: string): Photo {
  const found = ALL.get(slug);
  if (!found) throw new Error(`No photograph ${slug} in public/photos/index.json`);
  return found;
}

/** The six counties of the landing's strip, in order, each with its photograph. */
export const STRIP: readonly Photo[] = [
  "nairobi-jacaranda",
  "mombasa-old-town",
  "kisumu-lake-victoria",
  "nakuru-lake",
  "eldoret-town",
  "rongai-market",
].map(photo);

/** Explore's county tiles: a second view where a county has one, so the two pages do not repeat each other. */
const EXPLORE: readonly Photo[] = [photo("nairobi-golden-hour"), photo("mombasa-likoni-ferry"), ...STRIP.slice(2)];

/** Every photograph the site shows, credited on /credits. */
export const CREDITED: readonly Photo[] = [...new Map([...STRIP, ...EXPLORE].map((p) => [p.slug, p])).values()];

/** A county's anchor on /explore ("Uasin Gishu" → "uasin-gishu"); the same on both pages. */
export function countyAnchor(name: string): string {
  return name
    .normalize("NFKD")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

/** The photograph of a county on Explore, if one is vendored. */
export function photoOf(county: string): Photo | undefined {
  const anchor = countyAnchor(county);
  return EXPLORE.find((p) => countyAnchor(p.county) === anchor);
}
