import Link from "next/link";
import { getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import { Picture } from "@/components/landing/Picture";
import { ButtonLink } from "@/components/ui/ButtonLink";
import { EmptyState } from "@/components/ui/EmptyState";
import { countyAnchor, NATIONWIDE, photoOf, type Photo } from "@/lib/photos/photos";
import type { ExploreTeaser, PublicExplore } from "@/lib/public/public-data";

/** A problem's public page (app/(public)/explore/problems/[id]). */
export const problemHref = (id: string) => `/explore/problems/${encodeURIComponent(id)}`;

function Newest({ items, label, niche = true }: { items: readonly ExploreTeaser[]; label: string; niche?: boolean }) {
  return (
    <ul aria-label={label} className="flex flex-col divide-y divide-line">
      {items.slice(0, 3).map((item) => (
        <li key={item.id} className="py-2.5 first:pt-0 last:pb-0">
          <Link href={problemHref(item.id)} className="inline-flex min-h-11 flex-col justify-center font-semibold text-ink underline-offset-4 hover:underline">
            {item.title}
            {niche && item.niche ? <span className="text-sm font-normal text-ink-soft">{item.niche}</span> : null}
          </Link>
        </li>
      ))}
    </ul>
  );
}

/** A county's tile: its photograph (or tea country's) with the name and count over a night gradient, then its content. */
function Tile({ anchor, name, count, photo, eager = false, children }: { anchor: string; name: string; count: string; photo: Photo; eager?: boolean; children: ReactNode }) {
  return (
    <article aria-labelledby={`${anchor}-name`} className="flex h-full flex-col overflow-hidden rounded-[1.25rem] border border-line bg-field">
      <div className="relative">
        <Picture photo={photo} eager={eager} sizes="(min-width: 1024px) 23rem, (min-width: 640px) 50vw, 100vw" className="aspect-[16/9] w-full object-cover" />
        <span aria-hidden="true" className="tile-scrim absolute inset-0" />
        <div className="on-night absolute inset-x-0 bottom-0 flex items-end justify-between gap-3 p-4">
          <h3 id={`${anchor}-name`} className="font-display text-2xl leading-tight font-[560]">
            {name}
          </h3>
          <span className="shrink-0 text-sm font-semibold">{count}</span>
        </div>
      </div>
      <div className="p-4 sm:p-5">{children}</div>
    </article>
  );
}

/**
 * Explore (D-66; public): the published problems by county, each county a tile with its photograph (tea country's
 * where it has none of its own; the name over a night gradient) and its count, the newest three titles under it as
 * links to their public pages, the problems that name no county as "Nationwide"; then the niches as rows. "Seeded
 * example" when the summary is the demo seed's. One primary action, "Create an account". When GET /api/public/explore cannot be read, one sentence and one
 * way back.
 */
export async function ExploreContent({ explore }: { explore: PublicExplore | null }) {
  const t = await getTranslations("explore");
  // Problems that name no county are not in any county group: the remainder of the total is the nationwide group.
  const nationwide = explore ? explore.totals.problems - explore.counties.reduce((sum, county) => sum + county.count, 0) : 0;
  return (
    <div className="mx-auto w-full max-w-6xl px-4 pt-10 pb-20 sm:px-6 lg:pt-16 lg:pb-28">
      <header className="flex flex-col gap-6 sm:flex-row sm:items-end sm:justify-between sm:gap-10">
        <div>
          <p className="eyebrow">{t("eyebrow")}</p>
          <h1 className="mt-4 text-[2.5rem] leading-[1.05] text-ink lg:text-[3.5rem]">{t("title")}</h1>
          <p className="mt-4 max-w-[58ch] text-lg text-ink-soft">{t("lead")}</p>
          {explore ? (
            <p className="mt-4 flex flex-wrap items-center gap-3 font-semibold text-ink" data-explore="totals">
              {t("totals", explore.totals)}
              {explore.seeded ? <span className="demo-label">{t("seeded")}</span> : null}
            </p>
          ) : null}
        </div>
        <ButtonLink href="/signup" variant="primary" className="shrink-0">
          {t("signUp")}
        </ButtonLink>
      </header>

      {explore === null ? (
        <EmptyState sentence={t("empty")} action={t("emptyAction")} href="/" className="mt-12" data-explore="empty" />
      ) : explore.counties.length === 0 && explore.niches.length === 0 ? (
        <EmptyState sentence={t("none")} action={t("emptyAction")} href="/" className="mt-12" data-explore="none" />
      ) : (
        <>
          <section aria-labelledby="explore-counties" className="mt-14 lg:mt-16">
            <h2 id="explore-counties" className="text-2xl text-ink lg:text-3xl">
              {t("counties")}
            </h2>
            <ul className="mt-6 grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
              {explore.counties.map((county, index) => (
                <li key={county.code} id={countyAnchor(county.name)} className="scroll-mt-6">
                  <Tile
                    anchor={countyAnchor(county.name)}
                    name={county.name}
                    count={t("count", { count: county.count })}
                    photo={photoOf(county.name)}
                    eager={index === 0}
                  >
                    <Newest items={county.newest} label={t("newest", { place: county.name })} />
                  </Tile>
                </li>
              ))}
              {nationwide > 0 ? (
                <li id="nationwide" className="scroll-mt-6">
                  <Tile anchor="nationwide" name={t("nationwide")} count={t("count", { count: nationwide })} photo={NATIONWIDE}>
                    <p className="text-sm text-ink-soft">{t("nationwideNote")}</p>
                  </Tile>
                </li>
              ) : null}
            </ul>
          </section>

          <section aria-labelledby="explore-niches" className="mt-16 lg:mt-20">
            <h2 id="explore-niches" className="text-2xl text-ink lg:text-3xl">
              {t("niches")}
            </h2>
            <ul className="mt-6 flex flex-col divide-y divide-line border-y border-line">
              {explore.niches.map((niche) => (
                <li key={niche.id} className="grid grid-cols-1 gap-3 py-6 lg:grid-cols-[16rem_minmax(0,1fr)] lg:gap-10">
                  <div>
                    <h3 className="text-lg text-ink">{niche.name}</h3>
                    <p className="mt-0.5 text-sm text-ink-soft">{t("count", { count: niche.count })}</p>
                  </div>
                  <Newest items={niche.newest} label={t("newest", { place: niche.name })} niche={false} />
                </li>
              ))}
            </ul>
          </section>
        </>
      )}
    </div>
  );
}
