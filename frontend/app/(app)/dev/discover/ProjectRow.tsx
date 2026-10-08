import Link from "next/link";
import { useTranslations } from "next-intl";

import { problemHref } from "@/components/problem/problem";
import { ProblemLabelText } from "@/components/problem/ProblemLabelText";
import { titleLinkClass } from "@/components/ui/Button";
import { cn } from "@/components/ui/cn";

import { CardBand, discoverCardClass, discoverTitleClass } from "./CardList";
import { cardBadges, ChipList, MoreSummary, TrendBadge, WhyChip } from "./Chips";
import { cardChips, moreWhy, projectAnchor, type TrendingProject } from "./discover";

/**
 * One trending or new project (a published proposal's public teaser) beside the problem it solves (docs/spec/06 6.6,
 * AC-TREND-2), a compact card (P20): the summary, its chips, and at the foot the problem it solves, always there, links to its card and carries its provenance label. Its badge and
 * chips never count or name organisations (the API's rule); at most two badges, the rest under "More about this
 * project". A project has no page of its own here, so its title is not a link.
 */
export function ProjectRow({ item }: { item: TrendingProject }) {
  const t = useTranslations("discover");
  const { proposal, problem, trend, why } = item;
  const chips = cardChips(trend, why);
  const rest = moreWhy(trend, why);
  const anchor = projectAnchor(proposal.id);

  const badges = cardBadges([
    trend.trending && trend.badge ? <TrendBadge key="trend" badge={trend.badge} /> : null,
    ...chips.map((chip) => <WhyChip key={chip}>{chip}</WhyChip>),
  ]);

  return (
    <article
      id={anchor}
      aria-labelledby={`${anchor}-title`}
      data-project={proposal.id}
      data-trending={trend.trending ? "" : undefined}
      className={discoverCardClass}
    >
      <CardBand niche={proposal.teaser.niche} />
      <h3 id={`${anchor}-title`} className={discoverTitleClass}>
        {proposal.teaser.title ?? proposal.cert_id}
      </h3>
      {proposal.teaser.niche ? <p className="mt-1 text-sm text-ink-soft">{proposal.teaser.niche.label}</p> : null}
      {proposal.teaser.summary ? (
        <p className="mt-3 line-clamp-3 max-w-[65ch] [overflow-wrap:anywhere] text-ink">{proposal.teaser.summary}</p>
      ) : null}
      {badges ? <div className="mt-3 flex flex-wrap items-center gap-2">{badges}</div> : null}
      {rest.length > 0 ? (
        <details className="group mt-1">
          <MoreSummary>{t("moreProject")}</MoreSummary>
          <div className="mt-1 mb-2">
            <ChipList items={rest} />
          </div>
        </details>
      ) : null}
      {/* The problem it solves, as the card's foot: its card's link, niche and provenance. */}
      <div className="mt-auto pt-3">
        <div data-solves={problem.id} className="border-t border-line pt-3">
          <p className="text-sm text-ink-soft">{t("solves")}</p>
          <p>
            <Link
              href={problemHref(problem.id)}
              className={cn(titleLinkClass, "-my-2 inline-flex min-h-11 items-center font-semibold text-ink")}
            >
              {problem.title}
            </Link>
          </p>
          <p className="flex flex-wrap items-center gap-x-4 text-sm text-ink-soft">
            {problem.niche ? <span>{problem.niche.label}</span> : null}
            <ProblemLabelText problem={problem} />
          </p>
        </div>
      </div>
    </article>
  );
}
