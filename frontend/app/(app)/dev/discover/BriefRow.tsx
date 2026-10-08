import { useLocale, useTranslations } from "next-intl";

import { problemHref } from "@/components/problem/problem";
import { Badge } from "@/components/ui/Badge";
import { CompaniesIcon } from "@/components/ui/icons";
import { SharedTitle } from "@/components/motion/SharedTitle";
import { LinkPending } from "@/components/ui/LinkPending";
import Link from "next/link";
import { titleLinkClass } from "@/components/ui/Button";
import { StandaloneLink } from "@/components/ui/StandaloneLink";
import { formatCalendarDate } from "@/lib/format";

import { CardBand, CardFoot, discoverCardClass, discoverTitleClass } from "./CardList";
import { countryName, countyName, problemAnchor, startProposalHref, type CountyRef, type DiscoverBrief } from "./discover";

/**
 * One organisation's Problem Brief on Discover (REQ-DIR-05; docs/spec/06 6.2, 6.5), a compact card like a problem's:
 * its title linking to the problem card, one meta line (niche, place), the one "Posted by <organisation>" badge
 * (docs/spec/07 item 2: at most two), the budget band and the deadline on one line, the statement, then the proposals
 * answering it and "Start a proposal from this brief", which starts the idea with the problem linked (its pitch then
 * starts with the organisation chosen).
 */
export function BriefRow({ item, counties }: { item: DiscoverBrief; counties: readonly CountyRef[] }) {
  const t = useTranslations("discover");
  const tp = useTranslations("problem");
  const locale = useLocale();
  const { problem, brief } = item;
  const org = brief.org ?? problem.org ?? null;
  const place = countyName(problem.county_code, counties) ?? countryName(problem.country, locale);
  const titleId = `${problemAnchor(problem.id)}-title`;

  return (
    <article id={problemAnchor(problem.id)} aria-labelledby={titleId} data-brief={problem.id} className={discoverCardClass}>
      <CardBand niche={problem.niche} county={problem.county_code} />
      <h3 id={titleId} className={discoverTitleClass}>
        <Link href={problemHref(problem.id)} className={titleLinkClass}>
          <SharedTitle kind="problem" id={problem.id}>
            <span>{problem.title}</span>
          </SharedTitle>
          <LinkPending className="absolute -top-px left-4 sm:left-5" />
        </Link>
      </h3>
      <p className="mt-1 flex flex-wrap gap-x-4 text-sm text-ink-soft">
        {problem.niche ? <span>{problem.niche.label}</span> : null}
        <span>{place}</span>
      </p>
      {org ? (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Badge data-label="org_brief" tone="neutral" icon={<CompaniesIcon />}>
            {tp("label.org_brief", { org: org.name })}
          </Badge>
        </div>
      ) : null}
      <p className="mt-3 line-clamp-3 max-w-[65ch] [overflow-wrap:anywhere] text-ink">{problem.statement}</p>
      {/* The organisation's terms, the figures a developer weighs first. */}
      <p className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-sm font-semibold text-ink tabular-nums" data-brief-terms="">
        <span>{brief.budget_band ? t("briefBudget", { band: brief.budget_band.label }) : t("briefNoBudget")}</span>
        <span>
          {brief.deadline ? t("briefDeadline", { date: formatCalendarDate(locale, brief.deadline) }) : t("briefNoDeadline")}
        </span>
      </p>
      <CardFoot>
        <span data-proposals={item.proposal_count}>{t("proposals", { count: item.proposal_count })}</span>
        <StandaloneLink href={startProposalHref(problem.id)} className="text-sm" data-start-brief="">
          {t("startBrief")}
        </StandaloneLink>
      </CardFoot>
    </article>
  );
}
