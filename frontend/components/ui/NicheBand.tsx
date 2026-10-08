import { headers } from "next/headers";
import type { ReactNode } from "react";

import { Picture } from "@/components/landing/Picture";
import { photoWidths } from "@/lib/photos/files";
import { nichePhoto } from "@/lib/photos/niche";

import { cn } from "./cn";

/** The request asked to save data (the `Save-Data: on` client hint): no photograph is sent. */
export async function savesData(): Promise<boolean> {
  try {
    return (await headers()).get("save-data")?.trim().toLowerCase() === "on";
  } catch {
    return false; // outside a request (a test, a static render): nothing asked
  }
}

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
}

/**
 * A niche's or a county's photograph as a narrow band (D-67, P25): <picture> with AVIF and WebP, the file's own size
 * (no layout shift), lazy and decoded off the main thread, `alt=""` because the niche or county name is always shown
 * beside it. Where there is no photograph, or the request carries `Save-Data: on`, the kanga lattice band instead.
 * Never on the tracker (REQ-UX-05). A server component: no script.
 */
export async function NicheBand({ niche, county, children, className, sizes = "(min-width: 1280px) 26rem, (min-width: 640px) 45vw, 92vw" }: NicheBandProps) {
  const found = (await savesData()) ? undefined : nichePhoto({ niche, county });
  return (
    <div
      className={cn("niche-band h-16", found && children ? "niche-band-scrim" : null, !found && "niche-band-lattice", className)}
      data-niche-band={found ? found.slug : "lattice"}
    >
      {found ? <Picture photo={found} sizes={sizes} widths={photoWidths(found)} /> : null}
      {children ? <div className={cn("absolute inset-x-0 bottom-0 z-[1] p-3", found ? "text-on-night" : "text-ink")}>{children}</div> : null}
    </div>
  );
}
