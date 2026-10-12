import type { BandPosition } from "@/components/ui/NicheBand";
import { placePhotos } from "@/lib/photos/niche";

import type { OrgCard } from "./filters";

/** What a card's band shows: the photograph by its slug (null: the lattice) and the crop. */
export interface CardBand {
  photo: string | null;
  position: BandPosition;
}

/** Three crops, cycling card by card, so a photograph that recurs in a section never reads as a wallpaper tile. */
const CROPS: readonly BandPosition[] = ["top", "center", "bottom"];

/**
 * The bands of one niche section's cards, in order (P26). A card shows its own place only (lib/photos/niche.ts
 * placePhotos): the photographs of its HQ county that show the county itself, the next one of them card by card
 * (Nairobi's four cycle; a county with one keeps it); with none, its niche's photograph unless that shows a named
 * organisation's premises (no card carries another institution's campus, hall or station); else the lattice. The crop
 * cycles by index whatever the file. Deterministic and server-side: no script.
 */
export function sectionBands(orgs: readonly OrgCard[], sectionNiche: string | null | undefined): CardBand[] {
  return orgs.map((org, index) => {
    const position = CROPS[index % CROPS.length]!;
    const photos = placePhotos({ county: org.county?.code, niche: org.niches[0]?.slug ?? sectionNiche });
    return { photo: photos.length > 0 ? photos[index % photos.length]!.slug : null, position };
  });
}
