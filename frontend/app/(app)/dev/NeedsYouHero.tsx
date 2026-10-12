import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";

import { Chip, ChipMark } from "@/components/tracker/Chip";
import { isFinished, stageChip, type Summary } from "@/components/tracker/model";
import { clockUntil, DueClock, DueLine } from "@/components/tracker/When";
import { Avatar } from "@/components/ui/Avatar";
import { Badge } from "@/components/ui/Badge";
import { buttonClass } from "@/components/ui/Button";
import { Card, cardLinkClass } from "@/components/ui/Card";
import { LinkPending } from "@/components/ui/LinkPending";
import { cn } from "@/components/ui/cn";
import { formatShortDate } from "@/lib/format";

/**
 * Developer Home's "Needs you" card (D-52, P20): the page's most important object, so it is the one raised card. The
 * organisation's avatar, the idea as the card's one stretched link, the stage and the saffron "Your turn", and the
 * deadline beside the way in: the live clock (P26: days, hours, minutes in the figure face, the business days and the
 * date as its line) while the stage's window is open; the date as a figure with its business days otherwise. A hold has no deadline (its `due` is the day it
 * resumes) and an ended engagement none either: they keep the tracker's own line. The org portal keeps the shared
 * NeedsYouCard; this is the developer's Home only.
 */
export function NeedsYouHero({ item, href, action, now }: { item: Summary; href: string; action: string; now?: string }) {
  const t = useTranslations("tracker");
  const th = useTranslations("devHome");
  const locale = useLocale();
  const due = item.due && !isFinished(item.state) && item.state !== "ON_HOLD" ? item.due : null;
  const timed = Boolean(now && clockUntil(item, "developer"));
  const when = due
    ? due.overdue
      ? th("stats.deadlineOverdue")
      : due.business_days_left <= 0
        ? th("stats.deadlineToday")
        : th("stats.deadlineMeta", { count: due.business_days_left })
    : null;
  return (
    <Card
      as="article"
      interactive
      data-engagement={item.id}
      className="grid gap-5 sm:p-6 md:grid-cols-[minmax(0,1fr)_auto] md:items-center md:gap-8"
    >
      <div className="flex min-w-0 gap-4">
        <Avatar name={item.org_name} kind="org" size="lg" active />
        <div className="min-w-0">
          <h3 className="text-lg leading-snug font-semibold [overflow-wrap:anywhere] text-ink">
            <Link href={href} className={cardLinkClass}>
              {item.proposal_title}
              <LinkPending className="absolute top-0 left-0" />
            </Link>
          </h3>
          <p className="mt-1 text-sm text-ink-soft">{t("withOrg", { org: item.org_name })}</p>
          <p className="mt-3 flex flex-wrap items-center gap-2">
            <Chip kind={stageChip(item)}>{item.stage_label}</Chip>
            <Badge tone="warm" solid data-chip="turn" icon={<ChipMark kind="current" />}>
              {t("yourTurn")}
            </Badge>
          </p>
          {due ? null : (
            <p className="mt-2">
              <DueLine item={item} mine="developer" />
            </p>
          )}
        </div>
      </div>
      <div className="flex flex-wrap items-end justify-between gap-4 border-t border-line pt-4 md:flex-col md:items-end md:border-t-0 md:border-l md:py-1 md:pt-1 md:pl-8">
        {timed ? (
          <DueClock item={item} mine="developer" now={now} size="lg" className="md:items-end md:text-end" />
        ) : due ? (
          <p className="flex flex-col md:items-end" data-due={due.overdue ? "overdue" : "open"}>
            <time dateTime={due.due_on} className="font-figure text-3xl leading-none font-[720] tracking-[-0.03em] whitespace-nowrap text-ink tabular-nums">
              {formatShortDate(locale, due.due_on)}
            </time>
            {/* The business days under the date when the API sends no instant (or once overdue). */}
            <span className={cn("mt-1.5 text-sm", due.overdue ? "font-semibold text-error" : "text-ink-soft")}>{when}</span>
          </p>
        ) : null}
        <span aria-hidden="true" className={buttonClass("secondary", "shrink-0")}>
          {action}
        </span>
      </div>
    </Card>
  );
}
