import type { ReactNode } from "react";

import { Picture } from "@/components/landing/Picture";
import { useSavesData } from "@/lib/data-saver-request";
import { photoWidths } from "@/lib/photos/files";
import { nichePhoto, placePhotos } from "@/lib/photos/niche";
import { photo as photoBySlug } from "@/lib/photos/photos";

import { cn } from "./cn";

/** A band is a short strip: the 480 px files where they are vendored (P25-A), else P24's 800 px. */
function bandWidths(widths: readonly number[]): readonly number[] {
  return widths.includes(480) ? [480] : [800];
}

/** Where the photograph's crop sits (object-position): a list can vary it card by card, so one file never tiles. */
export type BandPosition = "top" | "center" | "bottom";
const POSITIONS: Readonly<Record<BandPosition, string>> = {
  top: "object-[50%_20%]",
  center: "object-[50%_50%]",
  bottom: "object-[50%_80%]",
};

export interface NicheBandProps {
  /** The niche's slug at any level ("microfinance-saccos" counts as financial services). */
  niche?: string | null;
  /** The county's reference code ("KE-30"): the public sector's photograph, or a company's HQ county. */
  county?: string | null;
  /** Text set on the band (a county's name on a company page): the night gradient goes under it. */
  children?: ReactNode;
  /** The band's height and shape (a card's narrow band by default). */
  className?: string;
  /** The `sizes` of the photograph (the band's width at each layout). */
  sizes?: string;
  /** A page-wide band (a problem page, a company page): every vendored size, not only the card band's 480 px. */
  wide?: boolean;
  /** The crop: the photograph's own centre unless given (P26: the Companies list cycles three crops). */
  position?: BandPosition;
  /**
   * The photograph chosen by the caller, by its slug (P26: a Companies section picks each card's own), or null for the
   * lattice; when not given, the band chooses from `niche` and `county`. Save-Data still drops it.
   */
  photo?: string | null;
  /** The page's first, largest picture (a company page's hero, its LCP): fetched at once, at high priority. */
  eager?: boolean;
  /**
   * The band stands for an organisation or something it posted (a Problem Brief): its place's photographs only, never
   * one of a named organisation's premises, which would read as its own (lib/photos/niche.ts placePhotos; P26).
   */
  forOrganisation?: boolean;
}

/**
 * A niche's or a county's photograph as a narrow band (D-67, P25): <picture> with AVIF and WebP, the file's own size
 * (no layout shift), lazy and decoded off the main thread, `alt=""` because the niche or county name is always shown
 * beside it. Where there is no photograph, or the request asks to save data (`Save-Data: on` or the data-saver switch,
 * P27), the kanga lattice band instead.
 * Never on the tracker (REQ-UX-05). A server component (synchronous, so cards can hold it): no script.
 */
export function NicheBand({
  niche,
  county,
  children,
  className,
  sizes = "(min-width: 1280px) 26rem, (min-width: 640px) 45vw, 92vw",
  wide = false,
  position,
  photo,
  eager = false,
  forOrganisation = false,
}: NicheBandProps) {
  const chosen =
    photo !== undefined
      ? photo
        ? photoBySlug(photo)
        : undefined
      : forOrganisation
        ? placePhotos({ niche, county })[0]
        : nichePhoto({ niche, county });
  const found = useSavesData() ? undefined : chosen;
  return (
    <div
      className={cn(
        "niche-band h-16",
        found && children ? "niche-band-scrim" : null,
        !found && "niche-band-lattice",
        className,
      )}
      data-niche-band={found ? found.slug : "lattice"}
      data-band-position={found && position ? position : undefined}
    >
      {found ? (
        <Picture
          photo={found}
          sizes={sizes}
          widths={wide ? photoWidths(found) : bandWidths(photoWidths(found))}
          className={position ? POSITIONS[position] : undefined}
          eager={eager}
        />
      ) : null}
      {children ? (
        <div className={cn("absolute inset-x-0 bottom-0 z-[1] p-3", found ? "text-on-night" : "text-ink")}>
          {children}
        </div>
      ) : null}
    </div>
  );
}
