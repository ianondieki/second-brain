// The photographs (D-66): licensed Kenyan photographs vendored under public/photos (AVIF and WebP at 800 and 1600 px,
// a 24 px blur), described by public/photos/index.json and credited on /credits. Until those files are merged, two
// placeholders drawn for the layout (public/placeholders, no credit) stand in, so the pages keep their real shape.

/** One photograph as public/photos/index.json describes it. */
export interface PhotoEntry {
  slug: string;
  /** The county it shows, by name ("Nairobi", "Uasin Gishu"). */
  county: string;
  caption: string;
  width: number;
  height: number;
  /** The exact attribution line to show (title, author, licence); empty for a placeholder. */
  credit: string;
}

/** A photograph with the folder its files are in. */
export interface Photo extends PhotoEntry {
  dir: string;
}

const PLACEHOLDER = { dir: "/placeholders", width: 1600, height: 1067, credit: "" } as const;

/** The six counties of the landing's strip, in order, each with its photograph. */
export const STRIP: readonly Photo[] = [
  { ...PLACEHOLDER, slug: "dusk", county: "Nairobi", caption: "" },
  { ...PLACEHOLDER, slug: "hills", county: "Nakuru", caption: "" },
  { ...PLACEHOLDER, slug: "dusk", county: "Mombasa", caption: "" },
  { ...PLACEHOLDER, slug: "hills", county: "Kisumu", caption: "" },
  { ...PLACEHOLDER, slug: "dusk", county: "Uasin Gishu", caption: "" },
  { ...PLACEHOLDER, slug: "hills", county: "Kiambu", caption: "" },
];

/** The credited photographs (the /credits page): none while the placeholders stand in. */
export const CREDITED: readonly Photo[] = STRIP.filter((photo) => photo.credit !== "");

/** A county's anchor on /explore ("Uasin Gishu" → "uasin-gishu"); the same on both pages. */
export function countyAnchor(name: string): string {
  return name
    .normalize("NFKD")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

/** The photograph of a county, if one is vendored. */
export function photoOf(county: string): Photo | undefined {
  const anchor = countyAnchor(county);
  return STRIP.find((photo) => countyAnchor(photo.county) === anchor);
}
