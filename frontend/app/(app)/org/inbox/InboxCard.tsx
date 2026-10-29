import { useLocale, useTranslations } from "next-intl";
import type { ReactNode } from "react";

import type { InboxItem } from "../data";
import { formatDay } from "../format";
import { ItemCard } from "../ItemCard";
import { StageChip } from "../StageChip";

/**
 * One Inbox proposal as a compact card (the organisation Home; D-52, D-67): the niche's photograph band (passed in by
 * the server page), the title, its niche and when it was sent, and the stage as the card's one chip. The whole card is
 * the link to the proposal; the chip is words here, not a second link. Nothing names another organisation it was sent
 * to (AC-REPO-6/a).
 */
export function InboxCard({ item, href, band }: { item: InboxItem; href: string; band?: ReactNode }) {
  const t = useTranslations("inbox");
  const locale = useLocale();
  const { teaser } = item.proposal;
  return (
    <ItemCard
      data-proposal={item.proposal.id}
      band={band}
      title={teaser.title ?? t("untitled")}
      href={href}
      meta={
        <span className="flex flex-wrap gap-x-4 gap-y-1">
          {teaser.niche ? <span>{teaser.niche.label}</span> : null}
          <time dateTime={item.pitched_at}>{t("sent", { date: formatDay(locale, item.pitched_at) })}</time>
        </span>
      }
      chips={[<StageChip key="stage" engagement={item.engagement} />]}
    />
  );
}
