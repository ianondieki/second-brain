import type { ReactNode } from "react";
import { preload } from "react-dom";

import { Picture } from "@/components/landing/Picture";
import { savesData } from "@/components/ui/NicheBand";
import { photoWidths } from "@/lib/photos/files";
import { greetingPhoto, type DayPart } from "@/lib/photos/greeting";

const SIZES = "(min-width: 1152px) 56rem, (min-width: 1024px) calc(100vw - 19rem), calc(100vw - 2rem)";

/**
 * Home's greeting (D-67, P25): a wide rounded band with Nairobi at this time of day behind the name, set in Fraunces
 * over a night gradient (the text keeps AA on any photograph). The photograph is the first screen's, so it is
 * preloaded at high priority and never lazy (the LCP budget); under Save-Data the band is the night colour alone.
 * Decorative (`alt=""`): the greeting says where and when. The children are the eyebrow, the h1, the lead and the
 * screen's one primary action.
 */
export async function GreetingBand({ part, children }: { part: DayPart; children: ReactNode }) {
  const photo = (await savesData()) ? null : greetingPhoto(part);
  const widths = photo ? photoWidths(photo) : [];
  if (photo) {
    const base = `${photo.dir}/${photo.slug}`;
    preload(`${base}-800.avif`, {
      as: "image",
      type: "image/avif",
      imageSrcSet: widths.map((w) => `${base}-${w}.avif ${w}w`).join(", "),
      imageSizes: SIZES,
      fetchPriority: "high",
    });
  }
  return (
    <div className="greeting-band on-night" data-greeting={photo ? photo.slug : "plain"}>
      {photo ? (
        <div className="greeting-photo" aria-hidden="true">
          <Picture photo={photo} sizes={SIZES} widths={widths} eager />
        </div>
      ) : null}
      <div className="greeting-body">{children}</div>
    </div>
  );
}
