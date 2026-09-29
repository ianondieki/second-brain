import Link from "next/link";
import { useTranslations } from "next-intl";

import { Chip } from "./Chip";
import { awaitsMe, isFinished, stageChip, type Party, type Summary } from "./model";
import { DueText } from "./When";

/**
 * One engagement in a list: the idea's title as the link to its tracker, the other party, and at most two chips
 * (docs/spec/07 item 2): where it stands (the stage's label with its mark) and, when it waits on the viewer's side,
 * "Your turn". The countdown follows as plain text.
 */
export function EngagementRow({ item, mine, href }: { item: Summary; mine: Party; href: string }) {
  const t = useTranslations("tracker");
  const turn = awaitsMe(item, mine);
  return (
    <article data-engagement={item.id} className="relative flex flex-col gap-1.5 border-t border-line py-5">
      <h3 className="text-lg [overflow-wrap:anywhere] text-ink">
        <Link
          href={href}
          className="underline decoration-line decoration-1 underline-offset-4 after:absolute after:inset-0 hover:decoration-jacaranda"
        >
          {item.proposal_title}
        </Link>
      </h3>
      <p className="text-sm [overflow-wrap:anywhere] text-ink-soft">
        {mine === "developer" ? t("withOrg", { org: item.org_name }) : t("fromDeveloper", { name: item.developer_name })}
      </p>
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5">
        <Chip kind={stageChip(item)}>{item.stage_label}</Chip>
        {turn ? (
          <span
            data-chip="turn"
            className="inline-flex items-center rounded-control bg-jacaranda px-2 py-0.5 text-sm font-semibold text-on-accent"
          >
            {mine === "developer" ? t("yourTurn") : t("ourTurn")}
          </span>
        ) : null}
        {item.due && !isFinished(item.state) ? (
          <DueText due={item.due} className={item.due.overdue ? "text-sm font-semibold text-error" : "text-sm text-ink-soft"} />
        ) : null}
      </div>
    </article>
  );
}
