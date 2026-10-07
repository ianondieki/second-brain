import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { Picture } from "@/components/landing/Picture";
import { ButtonLink } from "@/components/ui/ButtonLink";
import { EmptyState } from "@/components/ui/EmptyState";
import { Lattice } from "@/components/ui/Lattice";
import { countyAnchor, photoOf } from "@/lib/photos/photos";
import type { ExploreTeaser, PublicExplore } from "@/lib/public/public-data";

/** A problem's public page: the signed-in problem page (proxy.ts sends a visitor to log in first, then back). */
export const problemHref = (id: string) => `/problems/${encodeURIComponent(id)}`;

function Newest({ items, label, niche = true }: { items: readonly ExploreTeaser[]; label: string; niche?: boolean }) {
  return (
    <ul aria-label={label} className="flex flex-col divide-y divide-line">
      {items.slice(0, 3).map((item) => (
        <li key={item.id} className="py-2.5 first:pt-0 last:pb-0">
          <Link href={problemHref(item.id)} className="inline-flex min-h-11 flex-col justify-center font-semibold text-ink underline-offset-4 hover:underline">
            {item.title}
            {niche ? <span className="text-sm font-normal text-ink-soft">{item.niche}</span> : null}
          </Link>
        </li>
      ))}
    </ul>
  );
}

/**
 * Explore (D-66; public): the published problems by county, each county a tile with its photograph where one is
 * vendored (the name over a night gradient) and its count, the newest three titles under it as links; then the niches
 * as rows. One primary action, "Create an account". When GET /api/public/explore cannot be read, one sentence and one
 * way back.
 */
export async function ExploreContent({ explore }: { explore: PublicExplore | null }) {
  const t = await getTranslations("explore");
  return (
    <div className="mx-auto w-full max-w-6xl px-4 pt-10 pb-20 sm:px-6 lg:pt-16 lg:pb-28">
      <header className="flex flex-col gap-6 sm:flex-row sm:items-end sm:justify-between sm:gap-10">
        <div>
          <p className="eyebrow">{t("eyebrow")}</p>
          <h1 className="mt-4 text-[2.5rem] leading-[1.05] text-ink lg:text-[3.5rem]">{t("title")}</h1>
          <p className="mt-4 max-w-[58ch] text-lg text-ink-soft">{t("lead")}</p>
          {explore ? (
            <p className="mt-4 font-semibold text-ink" data-explore="totals">
              {t("totals", explore.totals)}
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
              {explore.counties.map((county, index) => {
                const anchor = countyAnchor(county.name);
                const photo = photoOf(county.name);
                return (
                  <li key={county.code} id={anchor} className="scroll-mt-6">
                    <article aria-labelledby={`${anchor}-name`} className="flex h-full flex-col overflow-hidden rounded-[1.25rem] border border-line bg-field">
                      <div className="relative">
                        {photo ? (
                          <Picture photo={photo} eager={index === 0} sizes="(min-width: 1024px) 23rem, (min-width: 640px) 50vw, 100vw" className="aspect-[16/9] w-full object-cover" />
                        ) : (
                          <span aria-hidden="true" className="flex aspect-[16/9] w-full flex-col justify-start bg-night">
                            <Lattice />
                          </span>
                        )}
                        <span aria-hidden="true" className="tile-scrim absolute inset-0" />
                        <div className="on-night absolute inset-x-0 bottom-0 flex items-end justify-between gap-3 p-4">
                          <h3 id={`${anchor}-name`} className="font-display text-2xl leading-tight font-[560]">
                            {county.name}
                          </h3>
                          <span className="shrink-0 text-sm font-semibold">{t("count", { count: county.count })}</span>
                        </div>
                      </div>
                      <div className="p-4 sm:p-5">
                        <Newest items={county.newest} label={t("newest", { place: county.name })} />
                      </div>
                    </article>
                  </li>
                );
              })}
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
