import Link from "next/link";
import { getLocale, getTranslations } from "next-intl/server";

import { formatMoment } from "@/components/problem/problem";
import { Chip } from "@/components/tracker/Chip";
import { AlertIcon } from "@/components/ui/icons";

import {
  caseHref,
  caseKind,
  caseReasons,
  caseTitle,
  outcome,
  visibility,
  VISIBILITY_CHIP,
  type Case,
} from "./moderation";

/** The decided line of a case ("Approved by … on …."), or null while it is open. */
export async function decidedLine(item: Case): Promise<string | null> {
  const result = outcome(item);
  if (!result || !item.decided_at) return null;
  const t = await getTranslations("adminModeration");
  const date = formatMoment(await getLocale(), item.decided_at);
  return item.decided_by
    ? t(`decidedBy.${result}`, { name: item.decided_by.display_name, date })
    : t(`decidedOn.${result}`, { date });
}

/**
 * One case in the queue (REQ-MOD-01): what it is about, its title (the way into the case), the start of its public
 * summary, and at most two tags (docs/spec/07 item 2): whether the subject can be seen now (or, once decided, the
 * outcome) and the first reason it was filed. When it was filed, or who decided it, is plain text.
 */
export async function CaseRow({ item }: { item: Case }) {
  const t = await getTranslations("adminModeration");
  const locale = await getLocale();
  const kind = caseKind(item.subject_type);
  const title = caseTitle(item) ?? t(`untitled.${kind}`);
  const seen = visibility(item);
  const result = outcome(item);
  const [reason] = caseReasons(item.reasons);
  const decided = await decidedLine(item);
  return (
    <li data-case={item.id} className="border-t border-line py-5 first:border-t-0 first:pt-0">
      <p className="text-sm font-medium text-ink-soft">{t(`kind.${kind}`)}</p>
      <h3 className="text-lg text-ink">
        <Link
          href={caseHref(item.id)}
          data-case-link=""
          className="inline-flex min-h-11 items-center font-semibold [overflow-wrap:anywhere] text-ink underline decoration-line decoration-1 underline-offset-4 hover:text-jacaranda hover:decoration-jacaranda"
        >
          {title}
        </Link>
      </h3>
      {item.preview.text ? (
        <p className="line-clamp-2 max-w-[65ch] [overflow-wrap:anywhere] text-ink-soft">{item.preview.text}</p>
      ) : null}
      <ul className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-ink-soft">
        {result ? (
          <li>
            <Chip kind={result === "approved" ? "completed" : "ended"}>{t(`outcome.${result}`)}</Chip>
          </li>
        ) : seen ? (
          <li>
            <Chip kind={VISIBILITY_CHIP[seen]}>{t(`visibility.${seen}`)}</Chip>
          </li>
        ) : null}
        {reason && !result ? (
          <li data-chip="reason" className="inline-flex items-center gap-1.5 font-semibold text-ink">
            <AlertIcon className="size-4 shrink-0" />
            {t(`reason.${reason}`)}
          </li>
        ) : null}
        <li>{decided ?? t("filed", { date: formatMoment(locale, item.created_at) })}</li>
      </ul>
    </li>
  );
}
