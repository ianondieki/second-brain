import { getLocale, getTranslations } from "next-intl/server";

import { formatMoment } from "@/components/problem/problem";
import { Chip } from "@/components/tracker/Chip";
import { Badge } from "@/components/ui/Badge";
import { AlertIcon, InfoIcon } from "@/components/ui/icons";
import Link from "next/link";

import { DataCell, DataRow, dataLinkClass } from "@/components/ui/DataTable";

import {
  caseHref,
  caseKind,
  caseKindLabel,
  caseReasons,
  caseTitle,
  messageReasons,
  outcomeChip,
  outcomeKey,
  reasonTone,
  visibility,
  VISIBILITY_CHIP,
  type Case,
} from "./moderation";

/** The decided line of a case ("Approved by … on …."), or null while it is open. */
export async function decidedLine(item: Case): Promise<string | null> {
  const result = outcomeKey(item);
  if (!result || !item.decided_at) return null;
  const t = await getTranslations("adminModeration");
  const date = formatMoment(await getLocale(), item.decided_at);
  return item.decided_by
    ? t(`decidedBy.${result}`, { name: item.decided_by.display_name, date })
    : t(`decidedOn.${result}`, { date });
}

/**
 * One case in the queue (REQ-MOD-01), a row of the queue's table: its title (the way into the case, the row header),
 * what it is about, when it was filed or who decided it, and at most two status badges (docs/spec/07 item 2): whether
 * the subject can be seen now (or, once decided, the outcome) and the first reason it was filed. `data-case-link`
 * marks the title's link (its own 44 px band).
 */
export async function CaseRow({ item }: { item: Case }) {
  const t = await getTranslations("adminModeration");
  const locale = await getLocale();
  const kind = caseKind(item.subject_type);
  const label = caseKindLabel(item);
  const kindText = label.key === "briefBy" ? t("kind.briefBy", { org: label.org }) : t(`kind.${label.key}`);
  // A message report's title is the queue's own words (the API's is English); its text never shows in the list.
  const title = kind === "message" ? t("untitled.message") : (caseTitle(item) ?? t(`untitled.${kind}`));
  const seen = visibility(item);
  const result = outcomeKey(item);
  const [reason] = caseReasons(item.reasons);
  const [reported] = kind === "message" ? messageReasons(item.reasons) : [];
  const decided = await decidedLine(item);
  const status = result ? (
    <Chip key="status" kind={outcomeChip(result)}>
      {t(`outcome.${result}`)}
    </Chip>
  ) : seen ? (
    <Chip key="status" kind={VISIBILITY_CHIP[seen]}>
      {t(`visibility.${seen}`)}
    </Chip>
  ) : null;
  // The first reason, while the case is open: a message report's in the reporter's words, else the check's.
  const flag = result ? null : reported ? (
    <Badge key="reason" data-chip="reason" tone="error" icon={<AlertIcon />}>
      {t(`message.reason.${reported}`)}
    </Badge>
  ) : reason ? (
    <Badge
      key="reason"
      data-chip="reason"
      tone={reasonTone(reason) === "flag" ? "error" : "accent"}
      icon={reasonTone(reason) === "flag" ? <AlertIcon /> : <InfoIcon />}
    >
      {t(`reason.${reason}`)}
    </Badge>
  ) : null;
  return (
    <DataRow data-case={item.id}>
      <DataCell head label={t("columns.case")} className="sm:w-[40%]">
        <Link href={caseHref(item.id)} data-case-link="" className={dataLinkClass}>
          {title}
        </Link>
        {item.preview.text ? (
          <p className="mt-1 line-clamp-2 max-w-[48ch] text-sm [overflow-wrap:anywhere] text-ink-soft">{item.preview.text}</p>
        ) : null}
      </DataCell>
      {/* Plain text, not a badge: the row keeps at most two status marks (docs/spec/07 item 2). */}
      <DataCell label={t("columns.kind")} nowrap>
        <span className="font-medium text-ink">{kindText}</span>
      </DataCell>
      <DataCell label={t("columns.when")} figure className="text-ink-soft">
        {decided ?? t("filed", { date: formatMoment(locale, item.created_at) })}
      </DataCell>
      <DataCell label={t("columns.status")}>
        <span className="flex flex-wrap items-center gap-x-4 gap-y-1">
          {status}
          {flag}
        </span>
      </DataCell>
    </DataRow>
  );
}
