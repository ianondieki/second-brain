import { getLocale, getTranslations } from "next-intl/server";

import type { ReadRefusal } from "@/components/tracker/data";
import { ClockTicker } from "@/components/ui/ClockTicker";
import { EmptyState } from "@/components/ui/EmptyState";
import { Section } from "@/components/ui/Section";
import { appNow } from "@/lib/api/server";

import { readDeadlines } from "./data";
import { DeadlineList } from "./DeadlineList";
import { addDays, byDay, gridSpan, nairobiDay, pickMonth, upcoming } from "./month";
import { dayName, monthName, MonthCalendar } from "./MonthCalendar";

const DAY = /^\d{4}-\d{2}-\d{2}$/;

export interface CalendarViewProps {
  /** "/dev/engagements" or "/org/engagements". */
  basePath: string;
  /** The organisation the calendar is for; none for the developer's own. */
  orgId?: string;
  /** `?org=` to keep in the view's links (members of several organisations). */
  orgQuery?: string;
  month?: string | string[];
  day?: string | string[];
  /** Whose calendar: its empty state's words. */
  side: "developer" | "org";
  /** Where an empty calendar's one action goes (Discover, or the organisation's Inbox). */
  emptyHref: string;
}

/**
 * The Calendar tab of Engagements (P27 track A; REQ-ENG-13), server-rendered for both sides: the month (`?month=`,
 * the current Nairobi month by default) and, under it, the list that is the content: a day's deadlines when one is
 * picked (`?day=`, from the grid), what is overdue, and what falls due in the next 30 days, the next one with the live
 * clock (the page's one ticker). Nothing due at all: one sentence and one action.
 */
export async function CalendarView({
  basePath,
  orgId,
  orgQuery,
  month: monthParam,
  day: dayParam,
  side,
  emptyHref,
}: CalendarViewProps) {
  const [t, locale] = await Promise.all([getTranslations("deadlines"), getLocale()]);
  // The platform's day: the API's clock (X-App-Now) of this request's first call (the session check).
  const today = nairobiDay(appNow());
  const month = pickMonth(monthParam, today);
  const span = gridSpan(month);
  const [grid, list] = await Promise.all([readDeadlines(span, orgId), readDeadlines({ to: addDays(today, 30) }, orgId)]);
  if (!grid.ok) return <ViewRefused refusal={grid.refusal} basePath={basePath} />;
  if (!list.ok) return <ViewRefused refusal={list.refusal} basePath={basePath} />;
  const now = list.value.now;
  const { overdue, next } = upcoming(list.value.items, nairobiDay(now));
  const picked =
    typeof dayParam === "string" && DAY.test(dayParam) && dayParam >= span.from && dayParam <= span.to
      ? dayParam
      : undefined;
  const ofDay = picked ? (byDay(grid.value.items).get(picked) ?? []) : [];
  const href = ({ month: m, day }: { month: string; day?: string }) => {
    const params = new URLSearchParams({ view: "calendar", month: m });
    if (day) params.set("day", day);
    if (orgQuery) params.set("org", orgQuery);
    return `${basePath}?${params}${day ? "#day-list" : ""}`;
  };

  if (grid.value.items.length === 0 && overdue.length === 0 && next.length === 0) {
    return (
      <EmptyState
        sentence={t(side === "developer" ? "emptyDev" : "emptyOrg", { month: monthName(locale, month) })}
        action={t(side === "developer" ? "emptyDevAction" : "emptyOrgAction")}
        href={emptyHref}
        data-deadlines="empty"
      />
    );
  }
  return (
    <div className="flex flex-col gap-12" data-deadlines="">
      <MonthCalendar month={month} today={nairobiDay(now)} items={grid.value.items} href={href} selected={picked} />
      {picked ? (
        <Section title={t("dayList", { date: dayName(locale, picked) })} headingId="day-list" data-deadlines-day={picked}>
          {ofDay.length > 0 ? (
            <DeadlineList items={ofDay} now={now} orgId={orgId} />
          ) : (
            <p className="text-ink-soft">{t("nextEmpty")}</p>
          )}
        </Section>
      ) : null}
      {overdue.length > 0 ? (
        <Section title={t("overdueTitle")} headingId="deadlines-overdue" data-deadlines-group="overdue">
          <DeadlineList items={overdue} now={now} orgId={orgId} />
        </Section>
      ) : null}
      <Section title={t("nextTitle")} headingId="deadlines-next" data-deadlines-group="next">
        {next.length > 0 ? (
          <DeadlineList items={next} now={now} orgId={orgId} clockFirst />
        ) : (
          <p className="text-ink-soft">{t("nextEmpty")}</p>
        )}
      </Section>
      {/* The live clock of the next thing due ticks from the page's one script. */}
      <ClockTicker />
    </div>
  );
}

/** A read the API refused: one sentence and one way on (docs/spec/07 item 4), under the page's own title. */
async function ViewRefused({ refusal, basePath }: { refusal: ReadRefusal; basePath: string }) {
  const t = await getTranslations("tracker");
  return refusal === "mfaSetup" ? (
    <EmptyState sentence={t("refused.mfaSetup")} action={t("turnOnMfa")} href="/settings/security" primary />
  ) : (
    <EmptyState sentence={t(`refused.${refusal}`)} action={t("back")} href={basePath} data-refusal={refusal} />
  );
}
