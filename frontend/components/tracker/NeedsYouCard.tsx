import Link from "next/link";
import { useTranslations } from "next-intl";

import { Avatar } from "@/components/ui/Avatar";
import { Badge } from "@/components/ui/Badge";
import { buttonClass } from "@/components/ui/Button";
import { Card, cardLinkClass } from "@/components/ui/Card";
import { LinkPending } from "@/components/ui/LinkPending";

import { Chip, ChipMark } from "./Chip";
import { isFinished, stageChip, type Party, type Summary } from "./model";
import { DueText } from "./When";

/**
 * One engagement that waits on the viewer, as a prominent card (D-52): the other party's avatar, the idea, the stage,
 * the deadline, and the way in. The card is one link, named by the idea's title and covering the whole card; the
 * "Open the tracker" affordance is the link's visual cue, not a second link. The chips stay the stage and "Your turn".
 */
export function NeedsYouCard({ item, mine, href, action }: { item: Summary; mine: Party; href: string; action: string }) {
  const t = useTranslations("tracker");
  const other = mine === "developer" ? item.org_name : item.developer_name;
  return (
    <Card as="article" interactive data-engagement={item.id} className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between sm:gap-6">
      <div className="flex min-w-0 gap-4">
        <Avatar name={other} kind={mine === "developer" ? "org" : "person"} size="lg" active />
        <div className="min-w-0">
          <h3 className="text-base [overflow-wrap:anywhere] text-ink">
            <Link href={href} className={cardLinkClass}>
              {item.proposal_title}
              <LinkPending className="absolute top-0 left-0" />
            </Link>
          </h3>
          <p className="mt-0.5 text-sm text-ink-soft">{mine === "developer" ? t("withOrg", { org: item.org_name }) : t("fromDeveloper", { name: item.developer_name })}</p>
          <p className="mt-2.5 flex flex-wrap items-center gap-x-5 gap-y-1.5">
            <Chip kind={stageChip(item)}>{item.stage_label}</Chip>
            <Badge tone="warm" solid data-chip="turn" icon={<ChipMark kind="current" />}>
              {mine === "developer" ? t("yourTurn") : t("ourTurn")}
            </Badge>
          </p>
          {item.due && !isFinished(item.state) ? (
            <p className="mt-2">
              <DueText due={item.due} className={item.due.overdue ? "text-sm font-semibold text-error" : "text-sm text-ink-soft"} />
            </p>
          ) : null}
        </div>
      </div>
      <span aria-hidden="true" className={buttonClass("secondary", "shrink-0 self-start")}>
        {action}
      </span>
    </Card>
  );
}
