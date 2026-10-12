import { useLocale, useTranslations } from "next-intl";
import type { ReactNode } from "react";

import { DeadlineClock } from "@/components/ui/DeadlineClock";

import { awaitsMe, eatParts, formatDate, isFinished, type Due, type Party, type Summary } from "./model";

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

type ClockItem = Pick<Summary, "state" | "due" | "developer_name" | "whose_turn">;

/**
 * The instant a card's live clock counts to (P26), or null where the card keeps DueLine's words: no instant from the
 * API, overdue (no negative time), ended, on hold (nothing is due; its date is the day it resumes) and, for the
 * organisation, an open question's answer-by date (the developer's deadline, never the organisation's own).
 */
export function clockUntil(item: ClockItem, mine: Party): string | null {
  const due = item.due;
  if (!due?.due_at || due.overdue || isFinished(item.state) || item.state === "ON_HOLD") return null;
  if (item.state === "INFO_REQUESTED" && mine === "org") return null;
  return due.due_at;
}

/**
 * A card's deadline (P26; REQ-TRACK-03): while the stage's window is open, the live clock (days, hours, minutes), the
 * business-days sentence as its line, warm under 24 hours when the step is the viewer's; otherwise, or without the
 * page's app-clock instant, DueLine as before. `className` is the clock's (DueLine keeps its own).
 */
export function DueClock({ item, mine, now, size, className }: { item: ClockItem; mine: Party; now?: string; size?: "sm" | "lg"; className?: string }) {
  const t = useTranslations("tracker");
  const until = clockUntil(item, mine);
  if (!until || !now || !item.due) return <DueLine item={item} mine={mine} />;
  return (
    <DeadlineClock
      until={until}
      now={now}
      labelWhenPast={t("chip.overdue")}
      mine={awaitsMe(item, mine)}
      words={<DueText due={item.due} />}
      size={size}
      className={className}
    />
  );
}
