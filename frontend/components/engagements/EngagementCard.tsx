import Link from "next/link";
import { useTranslations } from "next-intl";

import { SharedTitle } from "@/components/motion/SharedTitle";
import { Chip, ChipMark } from "@/components/tracker/Chip";
import { awaitsMe, stageChip, turnOf, type Party, type Summary } from "@/components/tracker/model";
import { UnreadLine } from "@/components/tracker/UnreadLine";
import { DueLine } from "@/components/tracker/When";
import { Avatar } from "@/components/ui/Avatar";
import { Badge } from "@/components/ui/Badge";
import { cardLinkClass } from "@/components/ui/Card";
import { cn } from "@/components/ui/cn";
import { LinkPending } from "@/components/ui/LinkPending";
import { NicheBand } from "@/components/ui/NicheBand";

import { StageDots } from "./StageDots";

export interface EngagementCardProps {
  item: Summary;
  /** The viewer's side: whose turn and the other party are read from it. */
  mine: Party;
  href: string;
  /** "organisation" (the developer's list, grouped under each idea): the other party is the title; "proposal": the idea is. */
  titleBy?: "proposal" | "organisation";
  /** The heading level under the page's own headings. */
  headingLevel?: 2 | 3;
  /** The idea's niche: its photograph as the card's top band (D-67; the lattice where there is none). */
  niche?: { slug: string } | null;
}

/**
 * One engagement as a card (P25, D-67), for both sides' lists: the other party's monogram and the title (the card's
 * one link, which morphs into the tracker's title), where it stands as five dots, then at most two chips (docs/spec/07
 * item 2: the stage in words and, when it waits on the viewer's side, the solid "Your turn"), otherwise who it waits
 * on, the countdown and any unread messages. Raised when it is the viewer's turn. With `niche`, the idea's niche
 * photograph tops the card (never on the tracker itself). Reusable by the organisation's lists.
 */
export function EngagementCard({ item, mine, href, titleBy = "proposal", headingLevel = 3, niche }: EngagementCardProps) {
  const t = useTranslations("tracker");
  const tc = useTranslations("engagementCard");
  const turn = turnOf(item, mine);
  const mineTurn = awaitsMe(item, mine);
  const other = mine === "developer" ? item.org_name : item.developer_name;
  const title = titleBy === "organisation" ? other : item.proposal_title;
  const Heading = headingLevel === 2 ? "h2" : "h3";
  const link = (
    <Link href={href} className={cardLinkClass}>
      {title}
      <LinkPending className="absolute top-2 left-1/2 -translate-x-1/2" />
    </Link>
  );
  return (
    <article
      data-engagement={item.id}
      data-turn={mineTurn ? "mine" : undefined}
      className={cn(
        "relative flex min-w-0 flex-col gap-3 rounded-panel border border-line bg-field p-4 sm:p-5",
        "transition-[border-color,box-shadow] duration-(--motion-fast) hover:border-accent-line",
        "has-[a:focus-visible]:outline-2 has-[a:focus-visible]:outline-offset-2 has-[a:focus-visible]:outline-accent",
        mineTurn && "shadow-card",
      )}
    >
      {niche !== undefined ? (
        <NicheBand niche={niche?.slug} className="-mx-4 -mt-4 mb-1 h-14 rounded-t-[15px] rounded-b-none sm:-mx-5 sm:-mt-5" />
      ) : null}
      <div className="flex min-w-0 items-start gap-3">
        <Avatar name={other} kind={mine === "developer" ? "org" : "person"} active={mineTurn} />
        <div className="min-w-0">
          <Heading className="font-sans text-base leading-snug font-semibold [overflow-wrap:anywhere] text-ink">
            {/* Titled by the idea, the title morphs into the tracker's (the same words); by the organisation it does not. */}
            {titleBy === "proposal" ? <SharedTitle kind="engagement" id={item.id}>{link}</SharedTitle> : link}
          </Heading>
          {titleBy === "proposal" ? (
            <p className="text-sm text-ink-soft">{mine === "developer" ? t("withOrg", { org: item.org_name }) : t("fromDeveloper", { name: item.developer_name })}</p>
          ) : null}
        </div>
      </div>
      <StageDots item={item} />
      <p className="flex flex-wrap items-center gap-2">
        <Chip kind={stageChip(item)}>{item.stage_label}</Chip>
        {mineTurn ? (
          <Badge tone="warm" solid data-chip="turn" icon={<ChipMark kind="current" />}>
            {mine === "developer" ? t("yourTurn") : t("ourTurn")}
          </Badge>
        ) : null}
      </p>
      <div className="mt-auto flex flex-col gap-1 text-sm">
        {turn.kind === "other" ? <p className="text-ink-soft">{tc("waitingOn", { name: other })}</p> : null}
        <DueLine item={item} mine={mine} />
        <UnreadLine count={item.unread_messages} />
      </div>
    </article>
  );
}
