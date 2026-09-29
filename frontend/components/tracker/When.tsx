import { useLocale, useTranslations } from "next-intl";

import { eatParts, formatDate, type Due } from "./model";

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

/** The stage's countdown in Kenyan business days, or how long it is overdue. */
export function DueText({ due, className }: { due: Due; className?: string }) {
  const t = useTranslations("tracker");
  const date = useDay()(due.due_on);
  const late = Math.abs(due.business_days_left);
  const text = due.overdue
    ? late > 0
      ? t("due.overdue", { count: late, date })
      : t("due.overdueToday", { date })
    : due.business_days_left <= 0
      ? t("due.today", { date })
      : t("due.left", { count: due.business_days_left, date });
  return (
    <span data-due={due.overdue ? "overdue" : "open"} className={className}>
      {text}
    </span>
  );
}
