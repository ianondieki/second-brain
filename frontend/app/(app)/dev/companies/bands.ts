import type { BandPosition } from "@/components/ui/NicheBand";
import { nichePhoto } from "@/lib/photos/niche";

import type { OrgCard } from "./filters";

/** What a card's band shows: NicheBand's inputs and the crop. */
export interface CardBand {
  niche: string | null;
  county: string | null;
  position: BandPosition;
}

/** Three crops, cycling card by card, so a photograph that recurs in a section never reads as a wallpaper tile. */
const CROPS: readonly BandPosition[] = ["top", "center", "bottom"];

/**
 * The bands of one niche section's cards, in order (P26). Each card shows its place first (its HQ county's photograph,
 * else its niche's or the section's), as the company page does; but a card whose photograph would repeat the card
 * before it takes the section's niche photograph instead (any level: "higher-education" shows Education's), so ten
 * Nairobi universities alternate the jacaranda and the campus rather than repeat one. The crop cycles by index
 * whatever the file. Deterministic (the same page draws the same bands) and server-side: no script.
 */
export function sectionBands(orgs: readonly OrgCard[], sectionNiche: string | null | undefined): CardBand[] {
  let previous: string | undefined;
  return orgs.map((org, index) => {
    const niche = org.niches[0]?.slug ?? sectionNiche ?? null;
    const county = org.county?.code ?? null;
    const position = CROPS[index % CROPS.length]!;
    const placeFirst = nichePhoto({ niche, county })?.slug;
    const alternative = sectionNiche ?? niche;
    const nicheOnly = alternative ? nichePhoto({ niche: alternative })?.slug : undefined;
    if (index > 0 && placeFirst !== undefined && placeFirst === previous && nicheOnly && nicheOnly !== previous) {
      previous = nicheOnly;
      return { niche: alternative, county: null, position };
    }
    previous = placeFirst;
    return { niche, county, position };
  });
}
