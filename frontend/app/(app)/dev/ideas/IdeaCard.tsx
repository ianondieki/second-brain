import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";

import { Card, cardLinkClass } from "@/components/ui/Card";
import { LinkPending } from "@/components/ui/LinkPending";

import { formatDay } from "./dates";
import { ideaHref, type MyProposalItem } from "./ideas";
import { IdeaStatusBadge } from "./IdeaStatusBadge";
import { hasUnpublishedChanges, ideaStatus } from "./status";
import { Badge } from "@/components/ui/Badge";

/**
 * One idea as a compact card (My ideas and Home's "My ideas", D-52), the whole card its link: the title, the niche and
 * last change, and at most two badges (docs/spec/07 item 2): the status and, for a published idea with saved edits,
 * "Unpublished changes" (in the accent: the developer can act on it). The heading level follows the page: h2 under the
 * My ideas title, h3 under Home's section heading.
 */
export function IdeaCard({ item, headingLevel = 2 }: { item: MyProposalItem; headingLevel?: 2 | 3 }) {
  const Heading = headingLevel === 3 ? "h3" : "h2";
  const t = useTranslations("ideas");
  const fields = useTranslations("ideaFields");
  const locale = useLocale();
  return (
    <Card as="article" variant="flat" padding="sm" interactive className="flex flex-col gap-1.5">
      <Heading className="font-sans text-base font-semibold tracking-[-0.005em] text-pretty [overflow-wrap:anywhere] text-ink">
        <Link href={ideaHref(item.id)} className={cardLinkClass}>
          {item.title?.trim() || t("untitled")}
          <LinkPending className="absolute -top-px left-0" />
        </Link>
      </Heading>
      <p className="flex flex-wrap gap-x-4 text-sm text-ink-soft">
        {item.niche ? <span>{item.niche.label}</span> : null}
        <span>{t("changed", { date: formatDay(locale, item.updated_at) })}</span>
      </p>
      <p className="flex flex-wrap items-center gap-x-5 gap-y-1">
        <IdeaStatusBadge status={ideaStatus(item.status, item.moderation_state)} />
        {hasUnpublishedChanges(item) ? (
          <Badge data-chip="" tone="accent" icon={<DotIcon />}>
            {fields("unpublishedChanges")}
          </Badge>
        ) : null}
      </p>
    </Card>
  );
}

/** A filled dot: saved edits wait to be published. */
function DotIcon() {
  return (
    <svg aria-hidden="true" focusable="false" viewBox="0 0 16 16">
      <circle cx="8" cy="8" r="4" fill="currentColor" />
    </svg>
  );
}
