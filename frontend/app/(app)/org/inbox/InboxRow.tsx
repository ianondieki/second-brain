import { useLocale, useTranslations } from "next-intl";

import type { ReactNode } from "react";

import type { InboxItem } from "../data";
import type { Membership } from "../membership";
import { editsShortlist } from "../shortlist";
import { MATURITY_KEY } from "../labels";
import { formatDay } from "../format";
import { ItemCard } from "../ItemCard";
import { StageChip } from "../StageChip";
import { ShortlistControl } from "./ShortlistControl";

/**
 * One proposal in the Inbox, Tier 1 only (the teaser the API returns), as a card (D-67, P25): the niche's photograph
 * band (passed in by the server page; decorative, the niche is named in the meta line), the title (a link to the
 * proposal page, an h2 under the page's h1), its niche and when it was sent, the summary, how far along it is and what
 * the developer asks for, then the stage chip at the foot (a link to the engagement's tracker).
 * Nothing names another organisation it was sent to (AC-REPO-6/a). With `org`, the card carries its shortlist star
 * (REQ-REPO-02), or the read-only mark for a member who cannot change the shortlist.
 */
export function InboxRow({
  item,
  href,
  trackerHref,
  org,
  band,
}: {
  item: InboxItem;
  href: string;
  trackerHref?: string;
  org?: Membership;
  band?: ReactNode;
}) {
  const t = useTranslations("inbox");
  const tp = useTranslations("orgProposal");
  const tf = useTranslations("ideaFields");
  const locale = useLocale();
  const { teaser } = item.proposal;
  const shortlisted = item.shortlisted ?? false;
  return (
    <ItemCard
      data-proposal={item.proposal.id}
      headingLevel={2}
      titleId={`title-${item.proposal.id}`}
      title={teaser.title ?? t("untitled")}
      href={href}
      band={band}
      meta={
        <span className="flex flex-wrap gap-x-4 gap-y-1">
          {teaser.niche ? <span>{teaser.niche.label}</span> : null}
          <time dateTime={item.pitched_at}>{t("sent", { date: formatDay(locale, item.pitched_at) })}</time>
        </span>
      }
      chips={[<StageChip key="stage" engagement={item.engagement} href={trackerHref} />]}
      control={
        org && (shortlisted || editsShortlist(org)) ? (
          <ShortlistControl org={org} proposalId={item.proposal.id} shortlisted={shortlisted} describedBy={`title-${item.proposal.id}`} />
        ) : undefined
      }
    >
      {teaser.summary ? <p className="mt-1 line-clamp-3 max-w-[64ch] text-ink">{teaser.summary}</p> : null}
      <dl className="mt-1 flex flex-wrap gap-x-5 gap-y-1 text-sm">
        <div className="flex gap-1.5">
          <dt className="text-ink-soft">{tp("maturityLabel")}</dt>
          <dd className="font-medium text-ink">{teaser.maturity ? tf(MATURITY_KEY[teaser.maturity]) : t("notStated")}</dd>
        </div>
        <div className="flex gap-1.5">
          <dt className="text-ink-soft">{tp("askLabel")}</dt>
          <dd className="font-medium text-ink">{teaser.ask ? t(`ask.${teaser.ask}`) : t("notStated")}</dd>
        </div>
      </dl>
    </ItemCard>
  );
}
