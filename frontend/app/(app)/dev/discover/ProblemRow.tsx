import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";

import { standaloneLinkClass } from "@/components/ui/Button";

import { ChipList, Chips, MoreSummary, TrendBadge } from "./Chips";
import {
  cardChips,
  countryName,
  countyName,
  discoverHref,
  formatSourceDate,
  moreWhy,
  problemAnchor,
  problemHref,
  projectAnchor,
  sourceUrl,
  startProposalHref,
  type CountyRef,
  type DiscoverQuery,
  type DiscoverSource,
  type TrendingProblem,
  type TrendingProject,
} from "./discover";

export const titleLinkClass =
  "-my-2 inline-flex min-h-11 items-center py-2 font-semibold [overflow-wrap:anywhere] text-ink " +
  "underline decoration-transparent decoration-1 underline-offset-[0.2em] hover:decoration-jacaranda";

export interface ProblemRowProps {
  item: TrendingProblem;
  counties: readonly CountyRef[];
  /** The trending projects that solve it (Problems view only; the Opportunity gap lists none). */
  projects?: readonly TrendingProject[];
  query: DiscoverQuery;
}

/**
 * One trending, new or under-served problem (REQ-TREND-02; docs/spec/06 6.6): its trend badge when it trends, its
 * title linking to the public problem card, niche, place and proposal count, the statement, at most two Why chips
 * (docs/spec/07 item 2), and "Start a proposal from this problem". The other chips, its newest sources and the
 * projects solving it sit under "More about this problem" (a native disclosure: no script).
 */
export function ProblemRow({ item, counties, projects = [], query }: ProblemRowProps) {
  const t = useTranslations("discover");
  const locale = useLocale();
  const { problem, trend, why, sources } = item;
  const place = countyName(problem.county_code, counties) ?? countryName(problem.country, locale);
  const chips = cardChips(trend, why);
  const rest = moreWhy(trend, why);
  const titleId = `${problemAnchor(problem.id)}-title`;

  return (
    <article
      id={problemAnchor(problem.id)}
      aria-labelledby={titleId}
      data-problem={problem.id}
      data-trending={trend.trending ? "" : undefined}
      className="flex min-w-0 flex-col gap-2 border-t border-line py-5"
    >
      <TrendBadge badge={trend.trending ? trend.badge : null} />
      <h3 id={titleId} className="text-lg leading-snug">
        <Link href={problemHref(problem.id)} className={titleLinkClass}>
          {problem.title}
        </Link>
      </h3>
      <p className="flex flex-wrap gap-x-4 text-sm text-ink-soft">
        {problem.niche ? <span>{problem.niche.label}</span> : null}
        <span>{place}</span>
        <span data-proposals={item.proposal_count}>{t("proposals", { count: item.proposal_count })}</span>
      </p>
      <p className="line-clamp-3 max-w-[65ch] [overflow-wrap:anywhere] text-ink">{problem.statement}</p>
      <Chips items={chips} className="mt-1" />

      <details className="group">
        <MoreSummary>{t("moreProblem")}</MoreSummary>
        <div className="mt-2 flex max-w-[65ch] flex-col gap-5 border-l-2 border-jacaranda-wash pl-4">
          {rest.length > 0 ? (
            <section>
              <h4 className="text-sm font-semibold text-ink">{t("whyTitle")}</h4>
              <div className="mt-1">
                <ChipList items={rest} />
              </div>
            </section>
          ) : null}
          <section>
            <h4 className="text-sm font-semibold text-ink">{t("sourcesTitle")}</h4>
            {sources.length > 0 ? (
              <ul className="mt-1 flex flex-col gap-4">
                {sources.map((source) => (
                  <li key={source.url}>
                    <Source source={source} />
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-1 text-ink-soft">{t("noSources")}</p>
            )}
          </section>
          {projects.length > 0 ? (
            <section>
              <h4 className="text-sm font-semibold text-ink">{t("solvedBy")}</h4>
              <ul className="mt-1 flex flex-col">
                {projects.map((project) => (
                  <li key={project.proposal.id}>
                    <Link
                      href={`${discoverHref({ ...query, view: "projects" })}#${projectAnchor(project.proposal.id)}`}
                      className={standaloneLinkClass}
                    >
                      {project.proposal.teaser.title ?? project.proposal.cert_id}
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
        </div>
      </details>

      <p>
        <Link href={startProposalHref(problem.id)} className={standaloneLinkClass}>
          {t("start")}
        </Link>
      </p>
    </article>
  );
}

/** A cited source: its publisher (a link to the page when it is a web address), date and the quoted words. */
function Source({ source }: { source: DiscoverSource }) {
  const t = useTranslations("discover");
  const locale = useLocale();
  const href = sourceUrl(source.url);
  const name = source.publisher ?? t("sourceUnnamed");
  const date = formatSourceDate(source.published_date, locale);
  return (
    <div className="flex flex-col gap-1">
      <p className="flex flex-wrap items-baseline gap-x-3">
        {href ? (
          <a href={href} rel="noopener noreferrer nofollow" target="_blank" className={standaloneLinkClass}>
            {name}
          </a>
        ) : (
          <span className="font-semibold text-ink">{name}</span>
        )}
        {date ? <span className="text-sm text-ink-soft">{t("sourcePublished", { date })}</span> : null}
      </p>
      {source.quote ? (
        <blockquote className="border-l border-line pl-3 text-sm [overflow-wrap:anywhere] text-ink">{source.quote}</blockquote>
      ) : null}
    </div>
  );
}
