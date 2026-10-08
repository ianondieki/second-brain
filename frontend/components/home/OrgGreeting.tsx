import type { ReactNode } from "react";
import { preload } from "react-dom";

import { Picture } from "@/components/landing/Picture";
import { savesData } from "@/components/ui/NicheBand";
import { DAY_PHOTOS, type DayPart } from "@/lib/photos/photos";

const SIZES = "(min-width: 1152px) 56rem, (min-width: 1024px) calc(100vw - 19rem), calc(100vw - 2rem)";

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
  if (photo) {
    const base = `${photo.dir}/${photo.slug}`;
    preload(`${base}-800.avif`, {
      as: "image",
      type: "image/avif",
      imageSrcSet: `${base}-800.avif 800w, ${base}-1600.avif 1600w`,
      imageSizes: SIZES,
      fetchPriority: "high",
    });
  }
  return (
    <div className="org-greet" data-greeting={photo ? photo.slug : "plain"}>
      {photo ? (
        <div className="org-greet-photo" aria-hidden="true">
          <Picture photo={photo} sizes={SIZES} eager />
        </div>
      ) : null}
      <div className="org-greet-body">{children}</div>
    </div>
  );
}
