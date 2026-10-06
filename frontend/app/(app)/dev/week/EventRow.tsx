import { getLocale, getTranslations } from "next-intl/server";

import { Badge } from "@/components/ui/Badge";
import { CheckIcon } from "@/components/ui/icons";
import { Row } from "@/components/ui/RowList";
import { formatTime } from "@/lib/format";

import { eventDay, eventHref, type WeekEvent } from "./week";

/**
 * One event as a row of a list (Home's strip, /dev/week): the title as the link to its page, then one line of plain
 * facts: when in Nairobi ("Sun 22 Nov · 18:00"), where (the venue's county, or "Online") and who organises it. A
 * reminder already set is its one status mark (docs/spec/07 item 2). `showDay` false leaves the day out of the time
 * where the list is already grouped by day.
 */
export async function EventRow({ event, showDay = true }: { event: WeekEvent; showDay?: boolean }) {
  const [t, locale] = await Promise.all([getTranslations("week"), getLocale()]);
  const time = formatTime(locale, event.starts_at);
  return (
    <Row
      data-week-event={event.id}
      href={eventHref(event.id)}
      title={event.title}
      meta={
        <span className="flex flex-wrap gap-x-4 gap-y-0.5">
          <span className="font-medium text-ink tabular-nums">
            {showDay ? t("row.when", { day: eventDay(locale, event.starts_at), time }) : time}
          </span>
          <span>{event.online ? t("row.online") : (event.county_name ?? event.venue)}</span>
          <span>{t("row.by", { organiser: event.organiser })}</span>
        </span>
      }
      badges={
        event.reminder
          ? [
              <Badge key="reminder" tone="ok" icon={<CheckIcon />} data-reminder-set="">
                {t("row.reminderSet")}
              </Badge>,
            ]
          : undefined
      }
    />
  );
}
