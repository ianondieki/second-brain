import { useLocale, useTranslations } from "next-intl";

import { Badge } from "@/components/ui/Badge";
import { Row } from "@/components/ui/RowList";

import { formatDay } from "./dates";
import { ideaHref, type MyProposalItem } from "./ideas";
import { IdeaStatusBadge } from "./IdeaStatusBadge";
import { hasUnpublishedChanges, ideaStatus } from "./status";

/** A filled dot: saved edits wait to be published. */
function DotIcon() {
  return (
    <svg aria-hidden="true" focusable="false" viewBox="0 0 16 16">
      <circle cx="8" cy="8" r="4" fill="currentColor" />
    </svg>
  );
}

/**
 * One idea in the list (a Row, the whole row its link): its title, the niche and last change, and at most two badges
 * (docs/spec/07 item 2): the status and, for a published idea with saved edits, "Unpublished changes" (in the accent:
 * the developer can act on it).
 */
export function IdeaRow({ item, headingLevel = 2 }: { item: MyProposalItem; headingLevel?: 2 | 3 }) {
  const t = useTranslations("ideas");
  const fields = useTranslations("ideaFields");
  const locale = useLocale();
  const status = <IdeaStatusBadge key="status" status={ideaStatus(item.status, item.moderation_state)} />;
  return (
    <Row
      title={item.title?.trim() || t("untitled")}
      href={ideaHref(item.id)}
      headingLevel={headingLevel}
      meta={
        <span className="flex flex-wrap gap-x-4">
          {item.niche ? <span>{item.niche.label}</span> : null}
          <span>{t("changed", { date: formatDay(locale, item.updated_at) })}</span>
        </span>
      }
      badges={
        hasUnpublishedChanges(item)
          ? [
              status,
              <Badge key="changes" data-chip="" tone="accent" icon={<DotIcon />}>
                {fields("unpublishedChanges")}
              </Badge>,
            ]
          : [status]
      }
    />
  );
}
