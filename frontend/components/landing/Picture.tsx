import type { Photo } from "@/lib/photos/photos";

import { cn } from "@/components/ui/cn";

/** P24's two sizes, vendored for every photograph. */
export const DEFAULT_WIDTHS: readonly number[] = [800, 1600];

/**
 * A vendored photograph (D-66): AVIF with a WebP fallback through <picture>, 800 and 1600 px for the given sizes, the
 * intrinsic width and height (no layout shift), lazy and decoded off the main thread (on the landing they sit below the
 * fold, never its LCP element; Explore's first one is `eager`), and the night colour until it paints (not the 24 px
 * blur: six more requests before the landing's first paint, which are LCP budget on Slow 4G). Decorative by default: the
 * link or heading beside it names the place.
 */
export function Picture({
  photo,
  sizes,
  alt = "",
  eager = false,
  className,
  widths = DEFAULT_WIDTHS,
}: {
  photo: Photo;
  sizes: string;
  alt?: string;
  /** The page's first photograph, in the first screen (Explore's first county on a phone): fetched at once, early. */
  eager?: boolean;
  className?: string;
  /** The widths vendored for it (lib/photos/files.ts photoWidths: 480 px where the card-band files exist). */
  widths?: readonly number[];
}) {
  const base = `${photo.dir}/${photo.slug}`;
  const set = (ext: string) => widths.map((w) => `${base}-${w}.${ext} ${w}w`).join(", ");
  const fallback = widths.find((w) => w >= 800) ?? widths[widths.length - 1] ?? 800;
  return (
    <picture>
      <source type="image/avif" srcSet={set("avif")} sizes={sizes} />
      <img
        src={`${base}-${fallback}.webp`}
        srcSet={set("webp")}
        sizes={sizes}
        width={photo.width}
        height={photo.height}
        alt={alt}
        loading={eager ? "eager" : "lazy"}
        // Below the first screen (lazy) photographs never compete with what paints first (P25: card bands).
        fetchPriority={eager ? "high" : "low"}
        decoding="async"
        className={cn("bg-night", className)}
      />
    </picture>
  );
}
