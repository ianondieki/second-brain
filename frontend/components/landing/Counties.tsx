import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { standaloneLinkClass } from "@/components/ui/Button";
import { cn } from "@/components/ui/cn";
import { countyAnchor, STRIP, type Photo } from "@/lib/photos/photos";

import { Picture } from "./Picture";

function Tile({ photo, copy }: { photo: Photo; copy: boolean }) {
  return (
    <li className="pan-tile">
      <Link
        href={`/explore#${countyAnchor(photo.county)}`}
        tabIndex={copy ? -1 : undefined}
        className="group relative block overflow-hidden rounded-[1.25rem] no-underline"
      >
        <Picture photo={photo} sizes="(min-width: 1024px) 18rem, 15rem" className="aspect-[4/5] w-full object-cover transition-transform duration-700 group-hover:scale-[1.03]" />
        <span aria-hidden="true" className="tile-scrim absolute inset-0" />
        <span className="on-night absolute inset-x-0 bottom-0 p-4 font-display text-2xl leading-tight font-[560]">{photo.county}</span>
      </Link>
    </li>
  );
}

/**
 * The county strip (D-66): six photographs, each a county's name set on the image over a night gradient and a link
 * to that county on /explore. The row pans slowly (globals.css .pan, a 24 s transform loop over two copies of the
 * row; the second hidden from assistive technology and the keyboard), pauses while hovered or focused, and stands
 * still, scrollable, under reduced motion. The photographs load lazily: the strip sits below the fold.
 */
export async function Counties() {
  const t = await getTranslations("landing.counties");
  return (
    <section aria-labelledby="counties-title" className="py-20 lg:py-28">
      <div className="mx-auto grid w-full max-w-6xl grid-cols-1 gap-x-10 gap-y-4 px-4 sm:px-6 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end">
        <div>
          <p className="eyebrow">{t("eyebrow")}</p>
          <h2 id="counties-title" className="mt-4 text-3xl text-ink lg:text-4xl">
            {t("title")}
          </h2>
          <p className="mt-4 max-w-[52ch] text-lg text-ink-soft">{t("lead")}</p>
        </div>
        <Link href="/explore" className={cn(standaloneLinkClass, "justify-self-start text-lg")}>
          {t("all")}
        </Link>
      </div>
      <div className="pan mt-10 lg:mt-12" role="group" aria-label={t("label")}>
        <div className="pan-track">
          {[false, true].map((copy) => (
            <ul key={String(copy)} aria-hidden={copy || undefined} className="pan-row">
              {STRIP.map((photo) => (
                <Tile key={photo.county} photo={photo} copy={copy} />
              ))}
            </ul>
          ))}
        </div>
      </div>
    </section>
  );
}
