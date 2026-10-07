import type { Photo } from "@/lib/photos/photos";

import { cn } from "@/components/ui/cn";

/**
 * A vendored photograph (D-66): AVIF with a WebP fallback through <picture>, 800 and 1600 px for the given sizes, the
 * intrinsic width and height (no layout shift), lazy and decoded off the main thread (on the landing they sit below the
 * fold, never its LCP element; Explore's first one is `eager`), and the 24 px blur as the background until it paints. Decorative by default: the
 * link or heading beside it names the place.
 */
export function Picture({
  photo,
  sizes,
  alt = "",
  eager = false,
  className,
}: {
  photo: Photo;
  sizes: string;
  alt?: string;
  /** The page's first photograph, in the first screen (Explore's first county on a phone): fetched at once, early. */
  eager?: boolean;
  className?: string;
}) {
  const base = `${photo.dir}/${photo.slug}`;
  return (
    <picture>
      <source type="image/avif" srcSet={`${base}-800.avif 800w, ${base}-1600.avif 1600w`} sizes={sizes} />
      <img
        src={`${base}-800.webp`}
        srcSet={`${base}-800.webp 800w, ${base}-1600.webp 1600w`}
        sizes={sizes}
        width={photo.width}
        height={photo.height}
        alt={alt}
        loading={eager ? "eager" : "lazy"}
        fetchPriority={eager ? "high" : undefined}
        decoding="async"
        className={cn("bg-cover bg-center", className)}
        style={{ backgroundImage: `url(${base}-blur.jpg)` }}
      />
    </picture>
  );
}
