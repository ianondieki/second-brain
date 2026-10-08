import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";

import { SharedTitle } from "@/components/motion/SharedTitle";
import { Badge } from "@/components/ui/Badge";
import { cardLinkClass } from "@/components/ui/Card";
import { LinkPending } from "@/components/ui/LinkPending";
import { NicheBand } from "@/components/ui/NicheBand";

import { formatDay } from "./dates";
import { ideaHref, type MyProposalItem } from "./ideas";
import { IdeaStatusBadge } from "./IdeaStatusBadge";
import { hasUnpublishedChanges, ideaStatus } from "./status";

/**
 * One idea as a card of My ideas (P25, D-67): its niche's photograph band (decorative: the niche is named under the
 * title), the title as the card's one link (it morphs into the idea page's title where View Transitions run), the niche
 * and the last change, then the foot: at most two badges (the status and, for a published idea with saved edits,
 * "Unpublished changes"; docs/spec/07 item 2) and the certificate id with the version when one is registered. Its three
 * parts sit on the grid's shared rows (subgrid), so a row of cards lines up its titles, meta and feet.
 */
export function IdeaTile({ item }: { item: MyProposalItem }) {
  const t = useTranslations("ideas");
  const fields = useTranslations("ideaFields");
  const locale = useLocale();
  const titleId = `idea-${item.id}-title`;
  return (
    <li className="card-sub">
      <article
        aria-labelledby={titleId}
        data-idea={item.id}
        className={
          "card-sub relative min-w-0 rounded-panel border border-line bg-field transition-[border-color,box-shadow] duration-(--motion-fast) " +
          "hover:border-accent-line hover:shadow-card has-[a:focus-visible]:outline-2 has-[a:focus-visible]:outline-offset-2 has-[a:focus-visible]:outline-accent"
        }
      >
        <div className="min-w-0">
          <NicheBand niche={item.niche?.slug} className="h-16 rounded-t-[15px] rounded-b-none" />
          <h2 id={titleId} className="px-5 pt-4 font-sans text-lg leading-snug font-semibold tracking-[-0.008em] [overflow-wrap:anywhere] text-ink">
            <SharedTitle kind="idea" id={item.id}>
              <Link href={ideaHref(item.id)} className={cardLinkClass}>
                {item.title?.trim() || t("untitled")}
                <LinkPending className="absolute top-2 left-1/2 -translate-x-1/2" />
              </Link>
            </SharedTitle>
          </h2>
        </div>
        <p className="flex flex-wrap gap-x-4 gap-y-1 px-5 text-sm text-ink-soft">
          {item.niche ? <span>{item.niche.label}</span> : null}
          <span>{t("changed", { date: formatDay(locale, item.updated_at) })}</span>
        </p>
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 self-end border-t border-line px-5 py-3">
          <span className="flex flex-wrap gap-2">
            <IdeaStatusBadge status={ideaStatus(item.status, item.moderation_state)} />
            {hasUnpublishedChanges(item) ? (
              <Badge data-chip="" tone="accent" icon={<DotIcon />}>
                {fields("unpublishedChanges")}
              </Badge>
            ) : null}
          </span>
          {item.cert_id ? (
            <span className="text-sm text-ink-soft">
              <span className="sr-only">{t("certificateId")} </span>
              <span className="font-mono text-[0.8125rem] tracking-[0.04em] text-ink">{item.cert_id}</span>
              {item.current_version_no ? <span className="ml-2">{t("version", { number: item.current_version_no })}</span> : null}
            </span>
          ) : null}
        </div>
      </article>
    </li>
  );
}

function DotIcon() {
  return (
    <svg aria-hidden="true" focusable="false" viewBox="0 0 16 16">
      <circle cx="8" cy="8" r="4" fill="currentColor" />
    </svg>
  );
}
