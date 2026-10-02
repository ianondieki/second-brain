import { useLocale, useTranslations } from "next-intl";
import type { ReactNode } from "react";

import { eatParts, formatDate, isFinished, type Due, type Party, type Summary } from "./model";

/** Formats moments as "23 Sep 2026, 14:05 EAT" (stored in UTC by the API, shown in Nairobi time; docs/spec/07 item 7). */
export function useEat(): (iso: string) => string {
  const t = useTranslations("tracker");
  const locale = useLocale();
  return (iso) => t("at", eatParts(iso, locale));
}

/** Formats calendar dates ("2 Oct 2026"). */
export function useDay(): (day: string) => string {
  const locale = useLocale();
  return (day) => formatDate(day, locale);
}

/** A moment on its own. */
export function Eat({ iso }: { iso: string }) {
  const eat = useEat();
  return <time dateTime={iso}>{eat(iso)}</time>;
}

/** A calendar date on its own. */
export function Day({ day }: { day: string }) {
  const format = useDay();
  return <time dateTime={day}>{format(day)}</time>;
}

/** The stage's countdown in Kenyan business days, or how long it is overdue; the date itself never splits across lines. */
export function DueText({ due, className }: { due: Due; className?: string }) {
  const t = useTranslations("tracker");
  const date = useDay()(due.due_on);
  const late = Math.abs(due.business_days_left);
  const nowrap = (chunks: ReactNode) => <span className="whitespace-nowrap">{chunks}</span>;
  const text = due.overdue
    ? late > 0
      ? t.rich("due.overdue", { count: late, date, nowrap })
      : t.rich("due.overdueToday", { date, nowrap })
    : due.business_days_left <= 0
      ? t.rich("due.today", { date, nowrap })
      : t.rich("due.left", { count: due.business_days_left, date, nowrap });
  return (
    <span data-due={due.overdue ? "overdue" : "open"} className={className}>
      {text}
    </span>
  );
}

/**
 * A list row's deadline line (the Engagements lists, Home's cards): the stage's countdown, except while on hold
 * ("Resumes 9 Oct 2026": nothing is due) and, for the organisation, an open question's answer-by date, named as the
 * developer's ("Answer from … due by 16 Oct 2026"), never as the organisation's own deadline. Nothing once ended.
 */
export function DueLine({ item, mine }: { item: Pick<Summary, "state" | "due" | "developer_name">; mine: Party }) {
  const t = useTranslations("tracker");
  const format = useDay();
  const due = item.due;
  if (!due || isFinished(item.state)) return null;
  const nowrap = (chunks: ReactNode) => <span className="whitespace-nowrap">{chunks}</span>;
  const date = format(due.due_on);
  const tone = due.overdue ? "text-sm font-semibold text-error" : "text-sm text-ink-soft";
  if (item.state === "ON_HOLD") {
    return (
      <span data-due="resumes" className="text-sm text-ink-soft">
        {t.rich("due.resumes", { date, nowrap })}
      </span>
    );
  }
  if (item.state === "INFO_REQUESTED" && mine === "org") {
    return (
      <span data-due={due.overdue ? "overdue" : "answer"} className={tone}>
        {t.rich(due.overdue ? "due.answerLate" : "due.answerBy", { name: item.developer_name, date, nowrap })}
      </span>
    );
  }
  return <DueText due={due} className={tone} />;
}
