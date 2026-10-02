import { useLocale, useTranslations } from "next-intl";

import { problemHref } from "@/components/problem/problem";
import { Badge } from "@/components/ui/Badge";
import { CompaniesIcon } from "@/components/ui/icons";
import { Row } from "@/components/ui/RowList";
import { StandaloneLink } from "@/components/ui/StandaloneLink";
import { formatCalendarDate } from "@/lib/format";

import { countryName, countyName, problemAnchor, startProposalHref, type CountyRef, type DiscoverBrief } from "./discover";

/**
 * One organisation's Problem Brief on Discover (REQ-DIR-05; docs/spec/06 6.2, 6.5), a compact card like a problem's:
 * its title linking to the problem card, one meta line (niche, place), the one "Posted by <organisation>" badge
 * (docs/spec/07 item 2: at most two), the budget band and the deadline on one line, the statement, then the proposals
 * answering it and "Start a proposal from this brief", which starts the idea with the problem linked and the
 * organisation named for the pitch.
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
    <Row
      id={problemAnchor(problem.id)}
      aria-labelledby={titleId}
      data-brief={problem.id}
      title={problem.title}
      titleId={titleId}
      href={problemHref(problem.id)}
      stretch={false}
      meta={
        <span className="flex flex-wrap gap-x-4">
          {problem.niche ? <span>{problem.niche.label}</span> : null}
          <span>{place}</span>
        </span>
      }
      badges={
        org
          ? [
              <Badge key="org" data-label="org_brief" tone="neutral" icon={<CompaniesIcon />}>
                {tp("label.org_brief", { org: org.name })}
              </Badge>,
            ]
          : undefined
      }
    >
      <p className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-ink" data-brief-terms="">
        <span>{brief.budget_band ? t("briefBudget", { band: brief.budget_band.label }) : t("briefNoBudget")}</span>
        <span>
          {brief.deadline ? t("briefDeadline", { date: formatCalendarDate(locale, brief.deadline) }) : t("briefNoDeadline")}
        </span>
      </p>
      <p className="mt-1 line-clamp-3 max-w-[65ch] [overflow-wrap:anywhere] text-ink">{problem.statement}</p>
      <p className="mt-2 flex flex-wrap items-center justify-between gap-x-6 gap-y-1 text-sm text-ink-soft">
        <span data-proposals={item.proposal_count}>{t("proposals", { count: item.proposal_count })}</span>
        <StandaloneLink href={startProposalHref(problem.id, org?.id)} className="text-sm" data-start-brief="">
          {t("startBrief")}
        </StandaloneLink>
      </p>
    </Row>
  );
}
