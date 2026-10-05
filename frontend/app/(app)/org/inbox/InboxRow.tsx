import { useLocale, useTranslations } from "next-intl";

import { Row } from "@/components/ui/RowList";

import type { InboxItem } from "../data";
import type { Membership } from "../membership";
import { editsShortlist } from "../shortlist";
import { MATURITY_KEY } from "../labels";
import { formatDay } from "../format";
import { StageChip } from "../StageChip";
import { ShortlistControl } from "./ShortlistControl";

/**
 * One proposal in the Inbox, Tier 1 only (the teaser the API returns), a Row: the title (a link to the proposal page,
 * an h2 under the page's h1), its niche and when it was sent, the stage badge (a link to the engagement's tracker),
 * the summary, and how far along it is and what the developer asks for.
 * Nothing names another organisation it was sent to (AC-REPO-6/a). With `org`, the row ends in its shortlist star
 * (REQ-REPO-02), or the read-only mark for a member who cannot change the shortlist.
 */
export function InboxRow({
  item,
  href,
  trackerHref,
  org,
}: {
  item: InboxItem;
  href: string;
  trackerHref?: string;
  org?: Membership;
}) {
  const t = useTranslations("inbox");
  const tp = useTranslations("orgProposal");
  const tf = useTranslations("ideaFields");
  const locale = useLocale();
  const { teaser } = item.proposal;
  const shortlisted = item.shortlisted ?? false;
  return (
    <Row
      data-proposal={item.proposal.id}
      headingLevel={2}
      title={teaser.title ?? t("untitled")}
      href={href}
      meta={
        <span className="flex flex-wrap gap-x-4 gap-y-1">
          {teaser.niche ? <span>{teaser.niche.label}</span> : null}
          <time dateTime={item.pitched_at}>{t("sent", { date: formatDay(locale, item.pitched_at) })}</time>
        </span>
      }
      badges={[<StageChip key="stage" engagement={item.engagement} href={trackerHref} />]}
      figure={
        org && (shortlisted || editsShortlist(org)) ? (
          <ShortlistControl org={org} proposalId={item.proposal.id} shortlisted={shortlisted} />
        ) : undefined
      }
    >
      {teaser.summary ? <p className="mt-1 line-clamp-3 max-w-[64ch] text-ink">{teaser.summary}</p> : null}
      <dl className="mt-1 flex flex-wrap gap-x-6 gap-y-1 text-sm">
        <div className="flex gap-1.5">
          <dt className="text-ink-soft">{tp("maturityLabel")}</dt>
          <dd className="font-medium text-ink">
            {teaser.maturity ? tf(MATURITY_KEY[teaser.maturity]) : t("notStated")}
          </dd>
        </div>
        <div className="flex gap-1.5">
          <dt className="text-ink-soft">{tp("askLabel")}</dt>
          <dd className="font-medium text-ink">{teaser.ask ? t(`ask.${teaser.ask}`) : t("notStated")}</dd>
        </div>
      </dl>
    </Row>
  );
}
