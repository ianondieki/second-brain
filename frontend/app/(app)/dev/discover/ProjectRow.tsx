import Link from "next/link";
import { useTranslations } from "next-intl";

import { problemHref } from "@/components/problem/problem";
import { ProblemLabelText } from "@/components/problem/ProblemLabelText";
import { titleLinkClass } from "@/components/ui/Button";
import { cn } from "@/components/ui/cn";
import { Description, DescriptionList } from "@/components/ui/DescriptionList";
import { Row } from "@/components/ui/RowList";

import { cardBadges, ChipList, MoreSummary, TrendBadge, WhyChip } from "./Chips";
import { cardChips, moreWhy, projectAnchor, type TrendingProject } from "./discover";

/**
 * One trending or new project (a published proposal's public teaser) beside the problem it solves (docs/spec/06 6.6,
 * AC-TREND-2), a Row: the problem is always there, links to its card and carries its provenance label. Its badge and
 * chips never count or name organisations (the API's rule); at most two badges, the rest under "More about this
 * project". A project has no page of its own here, so its title is not a link.
 */
export function ProjectRow({ item }: { item: TrendingProject }) {
  const t = useTranslations("discover");
  const { proposal, problem, trend, why } = item;
  const chips = cardChips(trend, why);
  const rest = moreWhy(trend, why);
  const anchor = projectAnchor(proposal.id);

  return (
    <Row
      id={anchor}
      aria-labelledby={`${anchor}-title`}
      data-project={proposal.id}
      data-trending={trend.trending ? "" : undefined}
      title={proposal.teaser.title ?? proposal.cert_id}
      titleId={`${anchor}-title`}
      meta={proposal.teaser.niche?.label}
      badges={cardBadges([
        trend.trending && trend.badge ? <TrendBadge key="trend" badge={trend.badge} /> : null,
        ...chips.map((chip) => <WhyChip key={chip}>{chip}</WhyChip>),
      ])}
    >
      {proposal.teaser.summary ? (
        <p className="mt-1 line-clamp-3 max-w-[65ch] [overflow-wrap:anywhere] text-ink">{proposal.teaser.summary}</p>
      ) : null}
      {/* The problem it solves, as a fact of the project: its card's link, niche and provenance. */}
      <DescriptionList dense data-solves={problem.id} className="mt-2">
        <Description label={t("solves")}>
          <Link
            href={problemHref(problem.id)}
            className={cn(titleLinkClass, "-my-2.5 inline-flex min-h-11 items-center font-semibold text-ink")}
          >
            {problem.title}
          </Link>
          <span className="flex flex-wrap gap-x-4 text-ink-soft">
            {problem.niche ? <span>{problem.niche.label}</span> : null}
            <ProblemLabelText problem={problem} />
          </span>
        </Description>
      </DescriptionList>
      {rest.length > 0 ? (
        <details className="group">
          <MoreSummary>{t("moreProject")}</MoreSummary>
          <div className="mt-1 mb-2">
            <ChipList items={rest} />
          </div>
        </details>
      ) : null}
    </Row>
  );
}
