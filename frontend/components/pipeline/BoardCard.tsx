import Link from "next/link";
import { useTranslations } from "next-intl";

import { ChipMark } from "@/components/tracker/Chip";
import { awaitsMe } from "@/components/tracker/model";
import { clockUntil, DueLine } from "@/components/tracker/When";
import { Avatar } from "@/components/ui/Avatar";
import { Badge } from "@/components/ui/Badge";
import { cardLinkClass } from "@/components/ui/Card";
import { cn } from "@/components/ui/cn";
import { DeadlineClock } from "@/components/ui/DeadlineClock";
import { ClockIcon } from "@/components/ui/status-icons";

import type { PipelineItem } from "./data";

/**
 * One engagement on the board (P27 track B; REQ-ENG-14): the compact EngagementCard of the organisation's side. The
 * idea's title as the card's one link; the deadline (the live clock's figure while the window is open, compact, its
 * business days left to the tracker; words otherwise; the page's ticker); the developer's monogram beside at most two
 * chips: "Our turn" when the step is the organisation's and the stalled mark ("No movement for N business days",
 * neutral, words with the clock mark). The stage chip is dropped: the column says it. The assignee, when there is one,
 * is a quiet line, not a chip.
 */
export function BoardCard({
  item,
  href,
  now,
  stalledAfter,
}: {
  item: PipelineItem;
  href: string;
  now: string;
  /** The policy's business days without an event before an engagement counts as stalled. */
  stalledAfter: number;
}) {
  const t = useTranslations("pipeline");
  const tt = useTranslations("tracker");
  const ours = awaitsMe(item, "org");
  const until = clockUntil(item, "org");
  return (
    <article
      data-engagement={item.id}
      data-stalled={item.stalled ? "" : undefined}
      className={cn(
        "relative flex min-w-0 flex-col gap-2.5 rounded-panel border border-line bg-field p-3.5",
        "transition-[border-color] duration-(--motion-fast) hover:border-accent-line",
        "has-[a:focus-visible]:outline-2 has-[a:focus-visible]:outline-offset-2 has-[a:focus-visible]:outline-accent",
        ours && "shadow-card",
      )}
    >
      {/* Under its column's h3. */}
      <h4 className="min-w-0 text-sm leading-snug font-semibold [overflow-wrap:anywhere] text-ink">
        <Link href={href} className={cardLinkClass}>
          {item.proposal_title}
        </Link>
      </h4>
      {/* The figure only: the business days are the tracker's line (the column is narrow). */}
      {until ? (
        <DeadlineClock size="xs" until={until} now={now} labelWhenPast={tt("chip.overdue")} mine={ours} />
      ) : (
        <DueLine item={item} mine="org" />
      )}
      <div className="flex flex-wrap items-center gap-2">
        <Avatar name={item.developer_name} kind="person" size="sm" active={ours} />
        {ours || item.stalled ? (
          <p className="flex min-w-0 flex-wrap items-center gap-2">
            {ours ? (
              <Badge tone="warm" solid data-chip="turn" icon={<ChipMark kind="current" />}>
                {tt("ourTurn")}
              </Badge>
            ) : null}
            {item.stalled ? (
              <Badge tone="neutral" data-chip="stalled" icon={<ClockIcon />}>
                {t("stalled", { count: stalledAfter })}
              </Badge>
            ) : null}
          </p>
        ) : null}
      </div>
      {item.team?.assignee ? (
        <p className="text-xs text-ink-soft" data-assignee={item.team.assignee.user_id}>
          {t("assignee", { name: item.team.assignee.display_name })}
        </p>
      ) : null}
    </article>
  );
}
