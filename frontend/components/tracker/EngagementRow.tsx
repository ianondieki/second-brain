import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/Badge";
import { Row } from "@/components/ui/RowList";

import { Chip, ChipMark } from "./Chip";
import { awaitsMe, stageChip, type Party, type Summary } from "./model";
import { UnreadLine } from "./UnreadLine";
import { DueLine } from "./When";

/**
 * One engagement in a list (a Row): the idea's title as the link to its tracker, the other party, and at most two
 * chips (docs/spec/07 item 2): where it stands (the stage's label with its mark) and, when it waits on the viewer's
 * side, the solid "Your turn" badge. The countdown follows as plain text. `titleBy="organisation"` (the developer's
 * Engagements page, already grouped under each proposal's heading): the organisation is the row's title and the
 * proposal is not repeated.
 */
export function EngagementRow({
  item,
  mine,
  href,
  titleBy = "proposal",
}: {
  item: Summary;
  mine: Party;
  href: string;
  titleBy?: "proposal" | "organisation";
}) {
  const t = useTranslations("tracker");
  const turn = awaitsMe(item, mine);
  const stage = <Chip kind={stageChip(item)}>{item.stage_label}</Chip>;
  return (
    <Row
      data-engagement={item.id}
      title={titleBy === "organisation" ? item.org_name : item.proposal_title}
      href={href}
      meta={
        titleBy === "organisation"
          ? undefined
          : mine === "developer"
            ? t("withOrg", { org: item.org_name })
            : t("fromDeveloper", { name: item.developer_name })
      }
      badges={
        turn
          ? [
              stage,
              // Icon + words + colour (docs/spec/07 item 6): the "current" mark in the badge's own colour.
              <Badge key="turn" tone="warm" solid data-chip="turn" icon={<ChipMark kind="current" />}>
                {mine === "developer" ? t("yourTurn") : t("ourTurn")}
              </Badge>,
            ]
          : [stage]
      }
    >
      <DueLine item={item} mine={mine} />
      <UnreadLine count={item.unread_messages} />
    </Row>
  );
}
