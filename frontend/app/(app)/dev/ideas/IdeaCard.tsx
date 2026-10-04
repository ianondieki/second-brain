import { useLocale, useTranslations } from "next-intl";

import { Badge } from "@/components/ui/Badge";
import { Row } from "@/components/ui/RowList";

import { formatDay } from "./dates";
import { ideaHref, type MyProposalItem } from "./ideas";
import { IdeaStatusBadge } from "./IdeaStatusBadge";
import { hasUnpublishedChanges, ideaStatus } from "./status";

/**
 * One idea as a row of a list (My ideas and Home's "My ideas"; P20: a list is rows, not a pile of cards), the whole
 * row its link: the title, the niche and last change, and at most two badges (docs/spec/07 item 2): the status and,
 * for a published idea with saved edits, "Unpublished changes" (in the accent: the developer can act on it). With
 * `version`, the registered version stands at the row's end from 640 px. The heading level follows the page: h2
 * under the My ideas title, h3 under Home's section heading. Put it in a RowList.
 */
export function IdeaCard({ item, headingLevel = 2, version = false }: { item: MyProposalItem; headingLevel?: 2 | 3; version?: boolean }) {
  const t = useTranslations("ideas");
  const fields = useTranslations("ideaFields");
  const locale = useLocale();
  const status = <IdeaStatusBadge key="status" status={ideaStatus(item.status, item.moderation_state)} />;
  return (
    <Row
      href={ideaHref(item.id)}
      // An h2 takes the display face from the base styles; a row's title is set in the text face whatever its level.
      title={<span className="font-sans font-semibold tracking-[-0.008em]">{item.title?.trim() || t("untitled")}</span>}
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
      figure={
        version && item.current_version_no ? (
          <span className="text-sm text-ink-soft">{t("version", { number: item.current_version_no })}</span>
        ) : undefined
      }
      figureFrom="sm"
    />
  );
}

/** A filled dot: saved edits wait to be published. */
function DotIcon() {
  return (
    <svg aria-hidden="true" focusable="false" viewBox="0 0 16 16">
      <circle cx="8" cy="8" r="4" fill="currentColor" />
    </svg>
  );
}
