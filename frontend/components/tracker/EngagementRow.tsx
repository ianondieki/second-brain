import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/Badge";
import { Row } from "@/components/ui/RowList";

import { Chip, ChipMark } from "./Chip";
import { awaitsMe, isFinished, stageChip, type Party, type Summary } from "./model";
import { DueText } from "./When";

/**
 * One engagement in a list (a Row): the idea's title as the link to its tracker, the other party, and at most two
 * chips (docs/spec/07 item 2): where it stands (the stage's label with its mark) and, when it waits on the viewer's
 * side, the solid "Your turn" badge. The countdown follows as plain text.
 */
export function EngagementRow({ item, mine, href }: { item: Summary; mine: Party; href: string }) {
  const t = useTranslations("tracker");
  const turn = awaitsMe(item, mine);
  const stage = <Chip kind={stageChip(item)}>{item.stage_label}</Chip>;
  return (
    <Row
      data-engagement={item.id}
      title={item.proposal_title}
      href={href}
      meta={mine === "developer" ? t("withOrg", { org: item.org_name }) : t("fromDeveloper", { name: item.developer_name })}
      badges={
        turn
          ? [
              stage,
              // Icon + words + colour (docs/spec/07 item 6): the "current" mark in the badge's own colour.
              <Badge key="turn" tone="accent" solid data-chip="turn" icon={<ChipMark kind="current" />}>
                {mine === "developer" ? t("yourTurn") : t("ourTurn")}
              </Badge>,
            ]
          : [stage]
      }
    >
      {item.due && !isFinished(item.state) ? (
        <DueText due={item.due} className={item.due.overdue ? "text-sm font-semibold text-error" : "text-sm text-ink-soft"} />
      ) : null}
    </Row>
  );
}
