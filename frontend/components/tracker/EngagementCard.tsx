import Link from "next/link";
import { useTranslations } from "next-intl";

import { Card, cardLinkClass } from "@/components/ui/Card";
import { LinkPending } from "@/components/ui/LinkPending";

import { Chip } from "./Chip";
import { stageChip, type Party, type Summary } from "./model";
import { DueLine } from "./When";

/** One engagement as a compact card (D-52, the lists that are not "Needs you"): the title as the link, the other party, the stage. */
export function EngagementCard({ item, mine, href }: { item: Summary; mine: Party; href: string }) {
  const t = useTranslations("tracker");
  return (
    <Card as="article" variant="flat" padding="sm" interactive data-engagement={item.id} className="flex flex-col gap-1.5">
      <h3 className="text-base [overflow-wrap:anywhere] text-ink">
        <Link href={href} className={cardLinkClass}>
          {item.proposal_title}
          <LinkPending className="absolute -top-px left-0" />
        </Link>
      </h3>
      <p className="text-sm text-ink-soft">{mine === "developer" ? t("withOrg", { org: item.org_name }) : t("fromDeveloper", { name: item.developer_name })}</p>
      <p className="flex flex-wrap items-center gap-x-5 gap-y-1">
        <Chip kind={stageChip(item)}>{item.stage_label}</Chip>
        <DueLine item={item} mine={mine} />
      </p>
    </Card>
  );
}
