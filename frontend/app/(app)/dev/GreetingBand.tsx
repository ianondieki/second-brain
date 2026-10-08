import type { ReactNode } from "react";

import { savesData } from "@/components/ui/NicheBand";
import { photoWidths } from "@/lib/photos/files";
import { greetingPhoto, type DayPart } from "@/lib/photos/greeting";
import type { Photo } from "@/lib/photos/photos";

/**
 * Below 40 rem (640 px; globals.css `.greeting-photo`) the photograph is a 9 rem strip above the words: the 480 px file.
 * Written as min/max-width, not range syntax: an HTML `media` attribute is not transpiled as globals.css is, and Safari
 * before 16.4 would match neither source and fall back to the 800 px WebP.
 */
export const PHONE_MEDIA = "(max-width: 639px)";
/** From 40 rem it fills the band behind the words, at most 56 rem wide, under a gradient: the 800 px file. */
export const WIDE_MEDIA = "(min-width: 640px)";

/**
 * Home's greeting (D-67, P25): a wide rounded band with Nairobi at this time of day behind the name, set in Fraunces
 * over a night gradient (the text keeps AA on any photograph). The photograph is the first screen's (the LCP element on
 * a phone), so it is preloaded at high priority and never lazy; under Save-Data the band is the night colour alone.
 * Decorative (`alt=""`): the greeting says where and when. The children are the eyebrow, the h1, the lead and the
 * screen's one primary action.
 */
export async function GreetingBand({ part, children }: { part: DayPart; children: ReactNode }) {
  const photo = (await savesData()) ? null : greetingPhoto(part);
  return (
    <div className="greeting-band on-night" data-greeting={photo ? photo.slug : "plain"}>
      {photo ? (
        <div className="greeting-photo" aria-hidden="true">
          <GreetingPicture photo={photo} />
        </div>
      ) : null}
      <div className="greeting-body">{children}</div>
    </div>
  );
}

/**
 * One file per layout, chosen by the viewport (`<source media>`), not by `sizes`: on a phone the strip is about 380 px
 * wide, which a 1.75 or 2 DPR screen would otherwise fetch at 800 px (a third more bytes before the LCP); the
 * photograph sits under a gradient as a mood, so 480 px is enough there (P25). AVIF first, WebP for the rest. It is in
 * the shell's HTML, so the browser's preload scanner takes it at once (a `preload()` from here reached only the RSC
 * payload, never the HTML); one file, at high priority, eagerly, and decoded with the first paint (no
 * `decoding="async"`: it is the LCP element, and an async decode paints it a frame after the rest).
 */
function GreetingPicture({ photo }: { photo: Photo }) {
  const base = `${photo.dir}/${photo.slug}`;
  const phone = photoWidths(photo).includes(480) ? 480 : 800;
  const sources = [
    { media: PHONE_MEDIA, width: phone },
    { media: WIDE_MEDIA, width: 800 },
  ];
  return (
    <picture>
      {sources.map(({ media, width }) => (
        <source key={`avif-${media}`} type="image/avif" media={media} srcSet={`${base}-${width}.avif`} />
      ))}
      {sources.map(({ media, width }) => (
        <source key={`webp-${media}`} type="image/webp" media={media} srcSet={`${base}-${width}.webp`} />
      ))}
      <img
        src={`${base}-800.webp`}
        width={photo.width}
        height={photo.height}
        alt=""
        loading="eager"
        fetchPriority="high"
        className="bg-night"
      />
    </picture>
  );
}
