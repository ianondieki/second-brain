import Link from "next/link";
import { useTranslations } from "next-intl";
import type { ReactNode } from "react";

import { DiscoverIcon } from "@/components/discover-icons";
import { Avatar } from "@/components/ui/Avatar";
import { BackLink } from "@/components/ui/BackLink";
import { ButtonLink } from "@/components/ui/ButtonLink";
import { NicheBand } from "@/components/ui/NicheBand";
import { placePhotos } from "@/lib/photos/niche";
import { Section } from "@/components/ui/Section";
import { StandaloneLink } from "@/components/ui/StandaloneLink";
import { Icon, type IconProps } from "@/components/ui/status-icons";

import { discoverHref } from "../discover/discover";
import { splitNicheLabel, type OrgCard } from "./filters";
import { VerificationBadge } from "./VerificationBadge";

/** Where a developer picks the idea to pitch: the pitch picker lives on an idea (/dev/ideas/{id}/pitch). */
const IDEAS_PATH = "/dev/ideas";

/**
 * One organisation's page (P26): the HQ county's photograph as the page's band with the county named on it (the
 * niche's where the county has none, unless it shows a named organisation's premises; the lattice otherwise; decorative, never a logo; fetched at once, as the
 * page's LCP), the monogram on its edge, the name in Fraunces, type and county, the badge verbatim and, for an E0
 * listing, what a pitch to it means (the held-tag sentence's shape, said before any pitch); the screen's one primary
 * action (problems in its first niche on Discover) and a way to pitch an idea; the facts as tiles; its niches as links
 * to Discover. Server-rendered, no script.
 */
export function OrgProfile({ org, back }: { org: OrgCard; back: string }) {
  const t = useTranslations("companies");
  const kinds = useTranslations("orgKind");
  const kind = kinds(org.kind);
  const first = org.niches[0];
  const hero = placePhotos({ county: org.county?.code, niche: first?.slug })[0];
  return (
    <article aria-labelledby="org-title" data-org={org.slug} className="flex max-w-4xl flex-col">
      <BackLink href={back}>{t("detailBack")}</BackLink>
      <NicheBand
        photo={hero?.slug ?? null}
        wide
        sizes="(min-width: 1024px) 56rem, 100vw"
        className="h-40 sm:h-56"
        // The page's largest picture in the first screen (its LCP): fetched at once.
        eager
      >
        {/* The county named on the photograph only when the photograph is of the county. */}
        {org.county && hero?.county_code === org.county.code ? (
          <span className="flex justify-end">
            <span className="inline-flex items-center gap-1.5 font-display text-lg font-semibold sm:text-xl">
              <PlaceIcon className="size-5 shrink-0" />
              {org.county.name}
            </span>
          </span>
        ) : null}
      </NicheBand>

      {/* The header's words and the niches line up with the words inside the fact tiles (their padding), the boxes with
          the photograph's edges. */}
      <header className="px-4 sm:px-5">
        {/* The seal on the photograph's lower edge: initials in the display face on a paper ring. */}
        <div className="relative -mt-10">
          <Avatar name={org.name} kind="org" size="xl" className="font-display ring-4 ring-paper" />
        </div>
        <div className="mt-4 flex flex-col gap-5 sm:flex-row sm:items-start sm:justify-between sm:gap-8">
          <div className="min-w-0">
            <h1
              id="org-title"
              className="text-2xl [overflow-wrap:anywhere] text-ink sm:text-[2.75rem] sm:leading-[1.04]"
            >
              {org.name}
            </h1>
            <p className="mt-2 text-ink-soft sm:text-[1.0625rem]">
              {org.county ? t("meta", { kind, county: org.county.name }) : kind}
            </p>
            <p className="mt-4">
              <VerificationBadge badge={org.badge} />
            </p>
            {org.badge.level === "e0" ? (
              <p data-held="" className="mt-2 max-w-[62ch] text-sm text-ink-soft">
                {t("heldUnclaimedHint", { name: org.name })}
              </p>
            ) : null}
          </div>
          {first ? (
            <div className="shrink-0 sm:pt-2">
              <ButtonLink variant="primary" href={discoverHref({ niche: first.slug })}>
                {t("findProblems", { niche: splitNicheLabel(first.label).name })}
              </ButtonLink>
            </div>
          ) : null}
        </div>
        <p className="mt-3">
          <StandaloneLink href={IDEAS_PATH}>{t("pitchIdea")}</StandaloneLink>
        </p>
      </header>

      <dl
        data-facts=""
        className="mt-8 grid grid-cols-[repeat(auto-fit,minmax(min(11rem,100%),1fr))] gap-3 sm:mt-10 sm:gap-4"
      >
        <Fact label={t("detailType")}>{kind}</Fact>
        <Fact label={t("detailCounty")}>
          {org.county ? org.county.name : <span className="font-normal text-ink-soft">{t("detailNone")}</span>}
        </Fact>
        {org.responsiveness ? (
          <Fact label={t("detailResponse")}>
            <span className="block font-figure text-2xl leading-none font-[720] tracking-[-0.03em] whitespace-nowrap tabular-nums">
              {t("responseFigure", { days: org.responsiveness.median_days, pct: org.responsiveness.answered_pct })}
            </span>
            <span className="mt-2 block text-sm font-normal text-ink-soft">{org.responsiveness.text}</span>
          </Fact>
        ) : null}
      </dl>

      {org.niches.length > 0 ? (
        <Section title={t("nichesTitle")} className="mt-10 px-4 sm:mt-12 sm:px-5">
          <ul className="flex flex-wrap gap-2.5">
            {org.niches.map((niche) => (
              <li key={niche.id} className="min-w-0">
                <Link
                  href={discoverHref({ niche: niche.slug })}
                  data-niche-link={niche.slug}
                  className={
                    "inline-flex min-h-11 max-w-full items-center gap-2 rounded-full border border-line bg-field px-4 py-2 " +
                    "text-sm font-semibold text-accent no-underline hover:border-accent-line hover:bg-wash-soft"
                  }
                >
                  <DiscoverIcon className="size-4 shrink-0" />
                  <span className="min-w-0 [overflow-wrap:anywhere]">{niche.label}</span>
                </Link>
              </li>
            ))}
          </ul>
        </Section>
      ) : null}
    </article>
  );
}

/** One fact as a tile: its name, then its value in the text face (a figure face only where the value is figures). */
function Fact({ label, children }: { label: ReactNode; children: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col rounded-panel border border-line bg-field p-4 sm:p-5">
      <dt className="text-sm font-semibold text-ink-soft">{label}</dt>
      <dd className="mt-2 text-lg leading-snug font-semibold [overflow-wrap:anywhere] text-ink">{children}</dd>
    </div>
  );
}

/** A place: a map pin (drawn like the set in components/ui/icons.tsx; decorative, the county is named beside it). */
function PlaceIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M10 17.5s-5.25-4.6-5.25-9a5.25 5.25 0 0 1 10.5 0c0 4.4-5.25 9-5.25 9Z" />
      <circle cx="10" cy="8.5" r="1.9" />
    </Icon>
  );
}
