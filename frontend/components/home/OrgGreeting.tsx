import type { ReactNode } from "react";
import { preload } from "react-dom";

import { savesData } from "@/components/ui/NicheBand";
import { DAY_PHOTOS, type DayPart } from "@/lib/photos/photos";

// On a phone the photograph sits under a gradient of 80 % or more, so the 480 px file is enough there (about 18 KB on
// Slow 4G instead of the 1600 px file's 150 KB, which a 2.6x screen would otherwise pick for its LCP).
const SIZES = "(min-width: 1152px) 56rem, (min-width: 1024px) calc(100vw - 19rem), (min-width: 640px) calc(100vw - 3rem), 180px";

/**
 * The organisation Home's greeting (D-67, P25), built as the developer Home's GreetingBand (wt/P25-C,
 * app/(app)/dev/GreetingBand.tsx, not yet on this branch): a wide rounded band with Nairobi at this time of day behind
 * the eyebrow, the name, the lead and the one primary action, over a night gradient that keeps the text AA on any
 * photograph. The photograph is the first screen's, so it is preloaded at high priority and never lazy; under
 * Save-Data the band is the night colour alone. Decorative (`alt=""`): the eyebrow names the place and time.
 * Once both branches meet, this gives way to GreetingBand (same props) and its CSS (portal.css `.org-greet*`) goes.
 */
export async function OrgGreeting({ part, children }: { part: DayPart; children: ReactNode }) {
  const photo = (await savesData()) ? null : DAY_PHOTOS[part];
  const base = photo ? `${photo.dir}/${photo.slug}` : "";
  if (photo) {
    preload(`${base}-480.avif`, {
      as: "image",
      type: "image/avif",
      imageSrcSet: `${base}-480.avif 480w, ${base}-800.avif 800w, ${base}-1600.avif 1600w`,
      imageSizes: SIZES,
      fetchPriority: "high",
    });
  }
  return (
    <div className="org-greet" data-greeting={photo ? photo.slug : "plain"}>
      {photo ? (
        <div className="org-greet-photo" aria-hidden="true">
          <picture>
            <source type="image/avif" srcSet={`${base}-480.avif 480w, ${base}-800.avif 800w, ${base}-1600.avif 1600w`} sizes={SIZES} />
            <img
              src={`${base}-480.webp`}
              srcSet={`${base}-480.webp 480w, ${base}-800.webp 800w, ${base}-1600.webp 1600w`}
              sizes={SIZES}
              width={photo.width}
              height={photo.height}
              alt=""
              loading="eager"
              fetchPriority="high"
              decoding="async"
              className="bg-night"
            />
          </picture>
        </div>
      ) : null}
      <div className="org-greet-body">{children}</div>
    </div>
  );
}
