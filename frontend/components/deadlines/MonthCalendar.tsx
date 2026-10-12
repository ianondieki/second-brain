import Link from "next/link";
import { getLocale, getTranslations } from "next-intl/server";

import { cn } from "@/components/ui/cn";
import { ChevronDownIcon } from "@/components/ui/icons";

import { KindMark } from "./KindMark";
import { byDay, isTurn, monthWeeks, shiftMonth, type Deadline } from "./month";

/** How many chips a day's cell shows before "+n more". */
export const CHIPS_PER_DAY = 2;

function intlLocale(locale: string) {
  return locale === "en" ? "en-GB" : `${locale}-KE`;
}

/** "October 2026" in the page's language. */
export function monthName(locale: string, month: string): string {
  return new Intl.DateTimeFormat(intlLocale(locale), { month: "long", year: "numeric", timeZone: "UTC" }).format(
    new Date(`${month}-01T00:00:00Z`),
  );
}

/** "16 October" in the page's language. */
export function dayName(locale: string, day: string): string {
  return new Intl.DateTimeFormat(intlLocale(locale), { day: "numeric", month: "long", timeZone: "UTC" }).format(
    new Date(`${day}T00:00:00Z`),
  );
}

export interface MonthCalendarProps {
  /** "2026-10" */
  month: string;
  /** Today in Nairobi, from the API's clock. */
  today: string;
  /** The month's deadlines (the grid's days, neighbours' included), sorted by instant. */
  items: readonly Deadline[];
  /** The address of a month or a day of this view: `?view=calendar` and the organisation kept by the caller. */
  href: (query: { month: string; day?: string }) => string;
  /** The day whose list is open (`?day=`), marked in the grid. */
  selected?: string;
}

/**
 * The Calendar tab's month (P27 track A; REQ-ENG-13), server-rendered: a table of weeks, Monday first, Nairobi days.
 * Each day shows up to two deadlines as chips (the kind's mark and a short title; overdue in the error tone with the
 * overdue words read out, the viewer's own turn with the saffron dot), then "+n more"; a day with deadlines is a link
 * to its list under the grid (`?day=`). Today is ringed and `aria-current="date"`. Under 640 px the chips give way to
 * dots under the day numbers, seven narrow columns, so the month never scrolls sideways; the list is the content.
 */
export async function MonthCalendar({ month, today, items, href, selected }: MonthCalendarProps) {
  const [t, locale] = await Promise.all([getTranslations("deadlines"), getLocale()]);
  const weeks = monthWeeks(month);
  const days = byDay(items);
  const weekday = (day: string, style: "long" | "short" | "narrow") =>
    new Intl.DateTimeFormat(intlLocale(locale), { weekday: style, timeZone: "UTC" }).format(
      new Date(`${day}T00:00:00Z`),
    );
  return (
    <section aria-labelledby="month-title" data-month={month}>
      <MonthHeader month={month} href={href} />
      <table aria-labelledby="month-title" className="w-full table-fixed border-collapse">
        <thead>
          <tr>
            {weeks[0].map(({ day }) => (
              <th
                key={day}
                scope="col"
                className="pb-2 text-center text-xs font-semibold text-ink-soft sm:text-start sm:ps-2 sm:text-sm"
              >
                <abbr title={weekday(day, "long")} className="no-underline">
                  <span className="sm:hidden">{weekday(day, "narrow")}</span>
                  <span className="max-sm:hidden">{weekday(day, "short")}</span>
                </abbr>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {weeks.map((week) => (
            <tr key={week[0].day}>
              {week.map(({ day, inMonth }) => {
                const list = days.get(day) ?? [];
                const isToday = day === today;
                const label = t("dayDeadlines", { date: dayName(locale, day), count: list.length });
                return (
                  <td
                    key={day}
                    data-day={day}
                    data-out={inMonth ? undefined : ""}
                    data-selected={day === selected ? "" : undefined}
                    className={cn(
                      "h-14 border border-line p-0.5 align-top sm:h-28 sm:p-1.5",
                      inMonth ? "bg-field" : "bg-paper",
                      day === selected && "outline-2 -outline-offset-2 outline-accent",
                    )}
                  >
                    <div className="flex h-full flex-col items-center gap-1 sm:items-stretch">
                      {list.length > 0 ? (
                        <Link
                          href={href({ month, day })}
                          aria-label={label}
                          aria-current={isToday ? "date" : undefined}
                          className={DAY_LINK}
                          data-day-link=""
                        >
                          <span className={dayNumberClass(isToday, inMonth, true)}>{Number(day.slice(8))}</span>
                        </Link>
                      ) : (
                        <span
                          aria-current={isToday ? "date" : undefined}
                          className={dayNumberClass(isToday, inMonth, false)}
                        >
                          {Number(day.slice(8))}
                        </span>
                      )}
                      {list.length > 0 ? (
                        <>
                          {/* Phones: a dot per deadline, up to three (the day's link says how many). */}
                          <span aria-hidden="true" className="flex gap-0.5 sm:hidden">
                            {list.slice(0, 3).map((item) => (
                              <span key={item.key} className={cn("size-1.5 rounded-full", dotTone(item))} />
                            ))}
                          </span>
                          <ul className="flex min-w-0 flex-col gap-1 max-sm:hidden">
                            {list.slice(0, CHIPS_PER_DAY).map((item) => (
                              <li key={item.key} data-chip-deadline={item.kind} title={item.title}>
                                <DayChip item={item} overdueWord={t("overdueTitle")} />
                              </li>
                            ))}
                            {list.length > CHIPS_PER_DAY ? (
                              <li>
                                <Link
                                  href={href({ month, day })}
                                  className="text-xs font-semibold text-accent underline decoration-1 hover:decoration-2"
                                  data-more=""
                                >
                                  {t("more", { count: list.length - CHIPS_PER_DAY })}
                                </Link>
                              </li>
                            ) : null}
                          </ul>
                        </>
                      ) : null}
                    </div>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

const MONTH_LINK =
  "inline-flex min-h-11 min-w-11 items-center justify-center gap-1 rounded-control px-2 font-semibold text-accent no-underline hover:underline";

/**
 * The month's name as the view's heading and the links to the months either side (‹ October 2026, December 2026 ›; the
 * names hidden under 640 px, read out in full). Above the grid, and above an empty month's one sentence too, so a
 * month with nothing due is never a dead end: the deadline next month is one press away.
 */
export async function MonthHeader({ month, href }: Pick<MonthCalendarProps, "month" | "href">) {
  const [t, locale] = await Promise.all([getTranslations("deadlines"), getLocale()]);
  const previous = shiftMonth(month, -1);
  const next = shiftMonth(month, 1);
  return (
    <div className="mb-4 flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
      <h2 id="month-title" className="text-2xl text-ink">
        {monthName(locale, month)}
      </h2>
      <p className="flex items-center gap-1">
        <Link
          href={href({ month: previous })}
          aria-label={t("previous", { month: monthName(locale, previous) })}
          className={MONTH_LINK}
          data-month-link="previous"
        >
          <ChevronDownIcon className="size-4 shrink-0 rotate-90" />
          <span className="max-sm:sr-only">{monthName(locale, previous)}</span>
        </Link>
        <Link
          href={href({ month: next })}
          aria-label={t("next", { month: monthName(locale, next) })}
          className={MONTH_LINK}
          data-month-link="next"
        >
          <span className="max-sm:sr-only">{monthName(locale, next)}</span>
          <ChevronDownIcon className="size-4 shrink-0 -rotate-90" />
        </Link>
      </p>
    </div>
  );
}

/**
 * A day with deadlines is a 44 px target at every width (docs/spec/07 item 6): on a phone its number fills it; from
 * 640 px the number is drawn 28 px and the link keeps 44 px around it, its 8 px overhang taken back by a negative
 * margin so the cell's layout is the 28 px one (the overhang lies over the cell's padding and the first chip, which is
 * not a control). The focus ring hugs the drawn number.
 */
const DAY_LINK =
  "group inline-flex size-11 shrink-0 items-center justify-center rounded-full no-underline sm:-m-2 sm:[--focus-offset:-6px]";

function dayNumberClass(today: boolean, inMonth: boolean, linked: boolean) {
  return cn(
    // A 44 px day on a phone (the same size linked or not, so the numbers line up), a figure in the figure face.
    "inline-flex size-11 shrink-0 items-center justify-center rounded-full font-figure text-sm tabular-nums sm:size-7",
    inMonth ? "text-ink" : "text-ink-soft",
    linked && "font-bold group-hover:bg-accent-wash",
    today && "ring-2 ring-accent",
  );
}

/** The phone's dot: overdue in the error colour, the viewer's own turn saffron, any other bloom. */
function dotTone(item: Deadline) {
  return item.overdue ? "bg-error" : isTurn(item) ? "bg-flourish" : "bg-accent";
}

/** A deadline in its day's cell: the kind's mark and the title on one line, cut with an ellipsis. */
function DayChip({ item, overdueWord }: { item: Deadline; overdueWord: string }) {
  return (
    <span
      data-tone={item.overdue ? "overdue" : isTurn(item) ? "mine" : "open"}
      className={cn(
        "flex min-w-0 items-center gap-1 rounded-sm px-1 py-0.5 text-xs leading-tight font-semibold",
        item.overdue ? "bg-error-wash text-error" : "bg-paper text-ink",
      )}
    >
      {isTurn(item) ? <span aria-hidden="true" className="size-1.5 shrink-0 rounded-full bg-flourish" /> : null}
      <KindMark kind={item.kind} className="size-3.5 shrink-0" />
      <span className="min-w-0 truncate">
        {item.overdue ? <span className="sr-only">{`${overdueWord}: `}</span> : null}
        {item.title}
      </span>
    </span>
  );
}
