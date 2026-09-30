import { getLocale, getTranslations } from "next-intl/server";

import { formatMoment } from "@/components/problem/problem";
import { Chip } from "@/components/tracker/Chip";
import { Badge } from "@/components/ui/Badge";
import { AlertIcon, InfoIcon } from "@/components/ui/icons";
import { Row } from "@/components/ui/RowList";

import {
  caseHref,
  caseKind,
  caseReasons,
  caseTitle,
  outcome,
  reasonTone,
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
 * One case in the queue (REQ-MOD-01), a Row: its title (the way into the case, an h2 under the page's h1), the meta
 * line (what it is about, then when it was filed or who decided it), at most two status badges
 * (docs/spec/07 item 2): whether the subject can be seen now (or, once decided, the outcome) and the first reason it
 * was filed; then the start of its public summary. The whole row is the link's target (a stretched link);
 * `data-case-link` marks that link.
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
  const status = result ? (
    <Chip key="status" kind={result === "approved" ? "completed" : "ended"}>
      {t(`outcome.${result}`)}
    </Chip>
  ) : seen ? (
    <Chip key="status" kind={VISIBILITY_CHIP[seen]}>
      {t(`visibility.${seen}`)}
    </Chip>
  ) : null;
  const flag =
    reason && !result ? (
      <Badge
        key="reason"
        data-chip="reason"
        tone={reasonTone(reason) === "flag" ? "error" : "accent"}
        icon={reasonTone(reason) === "flag" ? <AlertIcon /> : <InfoIcon />}
      >
        {t(`reason.${reason}`)}
      </Badge>
    ) : null;
  const shown = [status, flag].filter((badge) => badge !== null);
  return (
    <Row
      data-case={item.id}
      linkData={{ "data-case-link": "" }}
      headingLevel={2}
      title={title}
      href={caseHref(item.id)}
      meta={
        <span className="flex flex-wrap items-center gap-x-4 gap-y-1">
          {/* Plain meta text, not a badge: the row keeps at most two status marks (docs/spec/07 item 2). */}
          <span className="font-medium text-ink">{t(`kind.${kind}`)}</span>
          <span>{decided ?? t("filed", { date: formatMoment(locale, item.created_at) })}</span>
        </span>
      }
      badges={shown.length === 2 ? [shown[0], shown[1]] : shown.length === 1 ? [shown[0]] : undefined}
    >
      {item.preview.text ? (
        <p className="line-clamp-2 max-w-[65ch] [overflow-wrap:anywhere] text-ink-soft">{item.preview.text}</p>
      ) : null}
    </Row>
  );
}
