import Link from "next/link";
import { useTranslations } from "next-intl";

import { ChipList, Chips, MoreSummary, TrendBadge } from "./Chips";
import { cardChips, moreWhy, problemHref, projectAnchor, type TrendingProject } from "./discover";
import { titleLinkClass } from "./ProblemRow";

/**
 * One trending or new project (a published proposal's public teaser) beside the problem it solves (docs/spec/06 6.6,
 * AC-TREND-2): the problem is always there and links to its card. Its badge and chips never count or name
 * organisations (the API's rule); at most two chips, the rest under "More about this project".
 */
export function ProjectRow({ item }: { item: TrendingProject }) {
  const t = useTranslations("discover");
  const { proposal, problem, trend, why } = item;
  const chips = cardChips(trend, why);
  const rest = moreWhy(trend, why);
  const anchor = projectAnchor(proposal.id);
  const title = proposal.teaser.title ?? proposal.cert_id;

  return (
    <article
      id={anchor}
      aria-labelledby={`${anchor}-title`}
      data-project={proposal.id}
      data-trending={trend.trending ? "" : undefined}
      className="grid min-w-0 gap-4 border-t border-line py-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,17rem)] lg:gap-8"
    >
      <div className="flex min-w-0 flex-col gap-2">
        <TrendBadge badge={trend.trending ? trend.badge : null} />
        <h3 id={`${anchor}-title`} className="text-lg leading-snug font-semibold [overflow-wrap:anywhere] text-ink">
          {title}
        </h3>
        {proposal.teaser.niche ? <p className="text-sm text-ink-soft">{proposal.teaser.niche.label}</p> : null}
        {proposal.teaser.summary ? (
          <p className="line-clamp-3 max-w-[65ch] [overflow-wrap:anywhere] text-ink">{proposal.teaser.summary}</p>
        ) : null}
        <Chips items={chips} className="mt-1" />
        {rest.length > 0 ? (
          <details className="group">
            <MoreSummary>{t("moreProject")}</MoreSummary>
            <div className="mt-2 border-l-2 border-jacaranda-wash pl-4">
              <ChipList items={rest} />
            </div>
          </details>
        ) : null}
      </div>

      {/* The problem it solves, beside it from 1024 px and under it on phones (a rule marks the pairing). */}
      <div data-solves={problem.id} className="flex min-w-0 flex-col gap-1 border-l-2 border-jacaranda pl-4 lg:self-start">
        <p className="text-sm font-semibold text-ink-soft">{t("solves")}</p>
        <p className="leading-snug">
          <Link href={problemHref(problem.id)} className={titleLinkClass}>
            {problem.title}
          </Link>
        </p>
        {problem.niche ? <p className="text-sm text-ink-soft">{problem.niche.label}</p> : null}
      </div>
    </article>
  );
}
