import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { getLocale, getTranslations } from "next-intl/server";

import { DevNav } from "@/components/DevNav";
import { SignedInShell } from "@/components/SignedInShell";
import { InfoIcon, PencilIcon } from "@/components/ui/icons";
import { PageHeader } from "@/components/ui/PageHeader";
import { Section } from "@/components/ui/Section";
import { requireMe } from "@/lib/api/server";
import { homeFor } from "@/lib/auth/routing";
import { formatCalendarDate } from "@/lib/format";

import { trendPage } from "../../week/data";
import { safeHttps, WEEK_PATH } from "../../week/week";

export async function generateMetadata({ params }: PageProps<"/dev/trends/[id]">): Promise<Metadata> {
  const t = await getTranslations("week");
  const me = await requireMe();
  if (homeFor(me.side) !== "/dev") return { title: t("trend.pageTitle") };
  return { title: (await trendPage((await params).id)).title };
}

/**
 * Developer › a trend (REQ-DEV-02; D-60; P22 card B default (5)): the card's label as research cards carry theirs
 * ("Trend · AI-drafted, human-reviewed on {date}", or the seeded-example label for the demo's hand-written cards), the
 * title, the summary, then every source with its publisher, date, the quote as published and a link to read it there
 * (a new tab). Back to This week. A card that is not published is the not-found page. Developers only.
 */
export default async function TrendPage({ params }: PageProps<"/dev/trends/[id]">) {
  const me = await requireMe();
  const home = homeFor(me.side);
  if (home !== "/dev") redirect(home);
  const { id } = await params;
  const [t, locale, trend] = await Promise.all([getTranslations("week"), getLocale(), trendPage(id)]);
  const date = formatCalendarDate(locale, trend.reviewed_on);
  const label = trend.seeded_example ? "seeded" : "aiDrafted";

  return (
    <SignedInShell homeHref="/dev" nav={<DevNav current="home" />} wide>
      <article aria-labelledby="trend-title" className="flex max-w-3xl flex-col gap-12 lg:gap-14" data-trend={trend.id}>
        <PageHeader back={{ href: WEEK_PATH, label: t("trend.back") }} titleId="trend-title" title={trend.title}>
          {/* The label under the title as plain words, as a research card's in a list: no eyebrow above a heading, and
              no pill for a sentence this long (it wraps at 360 px). */}
          <p className="mt-3 flex max-w-[65ch] items-start gap-2 text-sm text-ink-soft">
            {label === "seeded" ? <InfoIcon className="mt-0.5 size-4 shrink-0" /> : <PencilIcon className="mt-0.5 size-4 shrink-0" />}
            <span data-label={label}>{t(`trend.label.${label}`, { date })}</span>
          </p>
          <p className="mt-5 max-w-[65ch] text-lg [overflow-wrap:anywhere] text-ink" data-summary="">
            {trend.summary}
          </p>
        </PageHeader>

        {trend.sources.length > 0 ? (
          <Section
            title={t("trend.sourcesHeading")}
            headingId="trend-sources"
            description={t("trend.sourcesCount", { count: trend.sources.length })}
          >
            <ol aria-labelledby="trend-sources" className="flex flex-col rounded-panel border border-line bg-field px-4 sm:px-6">
              {trend.sources.map((source, index) => {
                const href = safeHttps(source.url);
                return (
                  <li key={`${source.url}-${index}`} data-source="" className="flex min-w-0 flex-col gap-3 border-t border-line py-5 first:border-t-0">
                    <p className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                      <span className="font-semibold [overflow-wrap:anywhere] text-ink">{source.publisher}</span>
                      <span className="text-sm text-ink-soft">
                        {t("trend.publishedOn", { date: formatCalendarDate(locale, source.published_date) })}
                      </span>
                    </p>
                    <blockquote cite={href ?? undefined} className="max-w-[62ch] border-l-2 border-line pl-4 [overflow-wrap:anywhere] text-ink">
                      <p>{source.quote}</p>
                    </blockquote>
                    {href ? (
                      <a
                        href={href}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="-my-2.5 inline-flex min-h-11 max-w-full items-center self-start font-semibold [overflow-wrap:anywhere] text-accent underline decoration-1 hover:decoration-2"
                      >
                        <span>
                          {t("trend.open", { publisher: source.publisher })}
                          <span className="sr-only"> {t("trend.newTab")}</span>
                        </span>
                      </a>
                    ) : null}
                  </li>
                );
              })}
            </ol>
          </Section>
        ) : null}
      </article>
    </SignedInShell>
  );
}
