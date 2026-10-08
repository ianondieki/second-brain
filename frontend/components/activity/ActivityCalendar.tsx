import { getLocale, getTranslations } from "next-intl/server";
import type { CSSProperties } from "react";

import { formatCalendarDate } from "@/lib/format";

import { buildGrid, WEEKS, type Activity } from "./calendar";

/** A month's short name in the page's language ("Oct"; three letters in English, as lib/format.ts writes months). */
function monthName(locale: string, day: string): string {
  return new Intl.DateTimeFormat(locale === "en" ? "en-US" : `${locale}-KE`, { month: "short", timeZone: "UTC" }).format(
    new Date(`${day}T00:00:00Z`),
  );
}

/**
 * Your last 26 weeks (D-67, P25): one cell per day, Monday first, in the bloom scale (globals.css --heat-0..4, checked
 * with the dataviz method in light and dark), the months above, Mon/Wed/Fri beside, a Less…More legend, the total and
 * a line per kind of action. Each day's count and date show on hover; for assistive technology the grid is hidden
 * beside a table of the days with any action, and the busiest day is written out. The person's own counts only (the
 * API reads them as the caller).
 * A server component: no script.
 */
export async function ActivityCalendar({ activity, weeks = WEEKS }: { activity: Activity; weeks?: number }) {
  const [t, locale] = await Promise.all([getTranslations("activity"), getLocale()]);
  if (activity.total === 0) {
    return (
      <p className="text-ink-soft" data-activity="empty">
        {t("empty")}
      </p>
    );
  }
  const grid = buildGrid(activity);
  const busy = activity.days.filter((d) => d.count > 0);
  const kinds = activity.kinds.filter((k) => k.count > 0).sort((a, b) => b.count - a.count);
  const dayLabels = [t("mon"), "", t("wed"), "", t("fri"), "", ""];
  // The busiest day as words, so a day's count is readable without the hover tip (the table carries every day).
  const busiest = busy.reduce<(typeof busy)[number] | null>((top, d) => (!top || d.count > top.count ? d : top), null);

  return (
    <div className="cq" data-activity="">
      <div className="heat-frame" style={{ "--weeks": grid.weeks.length } as CSSProperties}>
        <div aria-hidden="true" className="heat">
          <div className="heat-months">
            {grid.months.map((m) => (
              <span key={m.date} className="heat-label" style={{ gridColumn: `${m.column + 2} / span 3` }}>
                {monthName(locale, m.date)}
              </span>
            ))}
          </div>
          <div className="heat-days">
            {dayLabels.map((label, row) => (
              <span key={row} className="heat-label heat-day">
                {label}
              </span>
            ))}
            {grid.weeks.flat().map((cell) => (
              <span
                key={cell.date}
                className="heat-cell"
                data-level={cell.level}
                data-future={cell.outside ? "" : undefined}
                data-tip={cell.outside ? undefined : t("tip", { count: cell.count, date: formatCalendarDate(locale, cell.date) })}
              />
            ))}
          </div>
        </div>

        {/* Beside the grid from a 44 rem column, under it before: the total, the busiest day, the legend, the kinds. */}
        <div className="heat-summary">
          <p className="figure font-semibold text-ink" data-activity-total="">
            {t("total", { total: activity.total, weeks })}
          </p>
          {busiest ? (
            <p className="figure text-sm text-ink" data-activity-busiest="">
              {t("busiest", { date: formatCalendarDate(locale, busiest.date), count: busiest.count })}
            </p>
          ) : null}
          <p aria-hidden="true" className="flex items-center gap-1.5 text-xs text-ink-soft" data-activity-legend="">
            <span>{t("less")}</span>
            {[0, 1, 2, 3, 4].map((step) => (
              <span key={step} className="heat-cell heat-swatch" data-level={step} />
            ))}
            <span>{t("more")}</span>
          </p>
          {kinds.length > 0 ? (
            <ul aria-label={t("kinds")} className="flex flex-wrap gap-x-5 gap-y-1 text-sm text-ink-soft" data-activity-kinds="">
              {kinds.map((k) => (
                <li key={k.kind} className="figure">
                  {t(`kind.${k.kind}`, { count: k.count })}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      </div>

      {/* Visually hidden by its box (a table ignores the sr-only size itself, and would widen the page). */}
      <div className="sr-only">
        <table data-activity-table="">
          <caption>{t("tableCaption", { weeks })}</caption>
          <thead>
            <tr>
              <th scope="col">{t("tableDate")}</th>
              <th scope="col">{t("tableCount")}</th>
            </tr>
          </thead>
          <tbody>
            {busy.map((d) => (
              <tr key={d.date}>
                <th scope="row">{formatCalendarDate(locale, d.date)}</th>
                <td>{d.count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
