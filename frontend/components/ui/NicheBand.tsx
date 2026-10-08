import { headers } from "next/headers";
import { use, type ReactNode } from "react";

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

/**
 * The same, read synchronously (React's `use`), so a band can sit inside the synchronous server components of cards.
 * Outside a request (a unit test, a static render) `headers()` throws at once: nothing was asked.
 */
export function useSavesData(): boolean {
  let pending: Promise<{ get(name: string): string | null }>;
  try {
    pending = headers();
  } catch {
    return false;
  }
  return use(pending).get("save-data")?.trim().toLowerCase() === "on";
}

/** A band is a short strip: the 480 px files where they are vendored (P25-A), else P24's 800 px. */
function bandWidths(widths: readonly number[]): readonly number[] {
  return widths.includes(480) ? [480] : [800];
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
 * Never on the tracker (REQ-UX-05). A server component (synchronous, so cards can hold it): no script.
 */
export function NicheBand({ niche, county, children, className, sizes = "(min-width: 1280px) 26rem, (min-width: 640px) 45vw, 92vw" }: NicheBandProps) {
  const found = useSavesData() ? undefined : nichePhoto({ niche, county });
  return (
    <div
      className={cn("niche-band h-16", found && children ? "niche-band-scrim" : null, !found && "niche-band-lattice", className)}
      data-niche-band={found ? found.slug : "lattice"}
    >
      {found ? <Picture photo={found} sizes={sizes} widths={bandWidths(photoWidths(found))} /> : null}
      {children ? <div className={cn("absolute inset-x-0 bottom-0 z-[1] p-3", found ? "text-on-night" : "text-ink")}>{children}</div> : null}
    </div>
  );
}
