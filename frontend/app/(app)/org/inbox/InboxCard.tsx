import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";

import { Card, cardLinkClass } from "@/components/ui/Card";
import { LinkPending } from "@/components/ui/LinkPending";

import type { InboxItem } from "../data";
import { formatDay } from "../format";
import { StageChip } from "../StageChip";

/**
 * One Inbox proposal as a compact card (the organisation Home, D-52): the title, its niche and when it was sent, and
 * the stage as the card's one chip. The whole card is the link to the proposal; the chip is words here, not a second
 * link. Nothing names another organisation it was sent to (AC-REPO-6/a).
 */
export function InboxCard({ item, href }: { item: InboxItem; href: string }) {
  const t = useTranslations("inbox");
  const locale = useLocale();
  const { teaser } = item.proposal;
  return (
    <Card as="article" variant="flat" padding="sm" interactive data-proposal={item.proposal.id} className="flex flex-col gap-1.5">
      <h3 className="text-base [overflow-wrap:anywhere] text-ink">
        <Link href={href} className={cardLinkClass}>
          {teaser.title ?? t("untitled")}
          <LinkPending className="absolute -top-px left-0" />
        </Link>
      </h3>
      <p className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-ink-soft">
        {teaser.niche ? <span>{teaser.niche.label}</span> : null}
        <time dateTime={item.pitched_at}>{t("sent", { date: formatDay(locale, item.pitched_at) })}</time>
      </p>
      <p className="flex flex-wrap items-center gap-x-5 gap-y-1">
        <StageChip engagement={item.engagement} />
      </p>
    </Card>
  );
}
