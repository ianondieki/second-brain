import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";

import { formatDate, problemHref, safeHttpsUrl } from "@/components/problem/problem";
import { ProblemLabelText } from "@/components/problem/ProblemLabelText";
import { standaloneLinkClass } from "@/components/ui/Button";
import { Row } from "@/components/ui/RowList";

import { cardBadges, ChipList, MoreSummary, TrendBadge, WhyChip } from "./Chips";
import {
  cardChips,
  countryName,
  countyName,
  discoverHref,
  moreWhy,
  problemAnchor,
  projectAnchor,
  startProposalHref,
  type CountyRef,
  type DiscoverQuery,
  type DiscoverSource,
  type TrendingProblem,
  type TrendingProject,
} from "./discover";
import { StandaloneLink } from "@/components/ui/StandaloneLink";

export interface ProblemRowProps {
  item: TrendingProblem;
  counties: readonly CountyRef[];
  /** The trending projects that solve it (Problems view only; the Opportunity gap lists none). */
  projects?: readonly TrendingProject[];
  query: DiscoverQuery;
}

/**
 * One trending, new or under-served problem (REQ-TREND-02; docs/spec/06 6.6), a Row: its title linking to the problem
 * card, one meta line (niche, place, proposal count, provenance), at most two badges (the trend badge when it trends,
 * then Why chips; docs/spec/07 item 2), the statement, and "Start a proposal from this problem". The other chips, its
 * newest sources and the projects solving it sit under "More about this problem" (a native disclosure: no script).
 * The title is the only link to the card (the row holds its own controls, so it is not stretched).
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
    <Row
      id={problemAnchor(problem.id)}
      aria-labelledby={titleId}
      data-problem={problem.id}
      data-trending={trend.trending ? "" : undefined}
      title={problem.title}
      titleId={titleId}
      href={problemHref(problem.id)}
      stretch={false}
      meta={
        <span className="flex flex-wrap gap-x-4">
          {problem.niche ? <span>{problem.niche.label}</span> : null}
          <span>{place}</span>
          <span data-proposals={item.proposal_count}>{t("proposals", { count: item.proposal_count })}</span>
          {/* Provenance in the page's language: developer-reported, AI-drafted and human-reviewed, or a seeded example. */}
          <ProblemLabelText problem={problem} />
        </span>
      }
      badges={cardBadges([
        trend.trending && trend.badge ? <TrendBadge key="trend" badge={trend.badge} /> : null,
        ...chips.map((chip) => <WhyChip key={chip}>{chip}</WhyChip>),
      ])}
    >
      <p className="mt-1 line-clamp-3 max-w-[65ch] [overflow-wrap:anywhere] text-ink">{problem.statement}</p>

      <details className="group">
        <MoreSummary>{t("moreProblem")}</MoreSummary>
        <div className="mt-1 mb-2 flex max-w-[65ch] flex-col gap-5">
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
              <p className="mt-1 text-ink-soft">{t(`noSources.${problem.source}`)}</p>
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
        <StandaloneLink href={startProposalHref(problem.id)}>
          {t("start")}
        </StandaloneLink>
      </p>
    </Row>
  );
}

/** A cited source: its publisher (a link to the page when it is a web address), date and the quoted words. */
function Source({ source }: { source: DiscoverSource }) {
  const t = useTranslations("discover");
  const locale = useLocale();
  const href = safeHttpsUrl(source.url); // https only: any other scheme is never a link
  const name = source.publisher ?? t("sourceUnnamed");
  const date = source.published_date ? formatDate(locale, source.published_date) : null;
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
