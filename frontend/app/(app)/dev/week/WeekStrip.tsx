import { getTranslations } from "next-intl/server";

import { RowList } from "@/components/ui/RowList";
import { Section } from "@/components/ui/Section";

import { EventRow } from "./EventRow";
import { TrendRow } from "./TrendRow";
import { WEEK_PATH, type Week } from "./week";

/**
 * Home's "This week" (REQ-DEV-02; D-60, D-61): up to three events near the developer (their county, or online) as
 * rows, then the trend of the day as one row (the word "Trend", its title as the link, one line of its summary), on
 * one flat sheet, drawn on the server with no script of its own; "See the week" is the section's link. Nothing near
 * and no trend: one sentence with the same link. When the read failed the section is left out (`week` null), never
 * the error page.
 */
export async function WeekStrip({ week }: { week: Week | null }) {
  if (!week) return null;
  const t = await getTranslations("week");
  const empty = week.events.length === 0 && !week.trend;
  return (
    <Section title={t("strip.title")} headingId="home-week" data-home="week" link={{ href: WEEK_PATH, label: t("strip.seeAll") }}>
      {empty ? (
        <p className="text-ink" data-week-empty="">
          {t("strip.empty")}
        </p>
      ) : (
        <div className="rounded-panel border border-line bg-field px-4 sm:px-6">
          <RowList rule={false} aria-label={t("strip.listLabel")}>
            {week.events.map((event) => (
              <EventRow key={event.id} event={event} />
            ))}
            {week.trend ? <TrendRow trend={week.trend} /> : null}
          </RowList>
        </div>
      )}
    </Section>
  );
}
