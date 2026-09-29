import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";

import {
  ideaHref,
  type MyProposalItem,
} from "./ideas";
import { formatDay } from "./dates";
import { hasUnpublishedChanges, ideaStatus } from "./status";
import { IdeaStatusBadge } from "./IdeaStatusBadge";

/**
 * One idea in the list: its title as the link, the niche, and at most two chips (docs/spec/07 item 2): the status
 * and, for a published idea with saved edits, "Unpublished changes".
 */
export function IdeaRow({ item }: { item: MyProposalItem }) {
  const t = useTranslations("ideas");
  const fields = useTranslations("ideaFields");
  const locale = useLocale();
  const changes = hasUnpublishedChanges(item);
  return (
    <article className="relative flex flex-col gap-1.5 border-t border-line py-5">
      <h2 className="text-lg [overflow-wrap:anywhere] text-ink">
        <Link
          href={ideaHref(item.id)}
          className="underline decoration-line decoration-1 underline-offset-4 after:absolute after:inset-0 hover:decoration-jacaranda"
        >
          {item.title?.trim() || t("untitled")}
        </Link>
      </h2>
      {item.niche ? <p className="text-sm text-ink-soft">{item.niche.label}</p> : null}
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-sm">
        <IdeaStatusBadge status={ideaStatus(item.status, item.moderation_state)} className="text-sm" />
        {changes ? (
          <span data-chip="" className="inline-flex items-center gap-1.5 font-medium text-ink">
            <span aria-hidden="true" className="size-2 rounded-full bg-jacaranda" />
            {fields("unpublishedChanges")}
          </span>
        ) : null}
        <span className="text-ink-soft">{t("changed", { date: formatDay(locale, item.updated_at) })}</span>
      </div>
    </article>
  );
}
