import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";

import { Card, cardLinkClass } from "@/components/ui/Card";
import { LinkPending } from "@/components/ui/LinkPending";

import { formatDay } from "./dates";
import { ideaHref, type MyProposalItem } from "./ideas";
import { IdeaStatusBadge } from "./IdeaStatusBadge";
import { ideaStatus } from "./status";

/** One idea as a compact card (Home's "My ideas", D-52): title link, niche and last change, the status badge. */
export function IdeaCard({ item }: { item: MyProposalItem }) {
  const t = useTranslations("ideas");
  const locale = useLocale();
  return (
    <Card as="article" variant="flat" padding="sm" interactive className="flex flex-col gap-1.5">
      <h3 className="text-base [overflow-wrap:anywhere] text-ink">
        <Link href={ideaHref(item.id)} className={cardLinkClass}>
          {item.title?.trim() || t("untitled")}
          <LinkPending className="absolute -top-px left-0" />
        </Link>
      </h3>
      <p className="flex flex-wrap gap-x-4 text-sm text-ink-soft">
        {item.niche ? <span>{item.niche.label}</span> : null}
        <span>{t("changed", { date: formatDay(locale, item.updated_at) })}</span>
      </p>
      <p>
        <IdeaStatusBadge status={ideaStatus(item.status, item.moderation_state)} />
      </p>
    </Card>
  );
}
