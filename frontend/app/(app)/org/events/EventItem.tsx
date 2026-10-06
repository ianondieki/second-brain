import { useLocale, useTranslations } from "next-intl";

import { EVENT_CHIP } from "@/components/events/status";
import type { EventOut } from "@/components/events/event-draft";
import { eventDay } from "@/components/events/when";
import { Chip } from "@/components/tracker/Chip";
import { Row } from "@/components/ui/RowList";
import { formatTime } from "@/lib/format";

/**
 * One of the organisation's events in its list (REQ-DEV-02), a compact card (RowList cards) as the Briefs': the title
 * linking to its page, when (Nairobi) and where on one line, and one status mark (In review, Published, Not approved,
 * Cancelled; docs/spec/07 item 2: at most two).
 */
export function EventItem({ event, href }: { event: EventOut; href: string }) {
  const t = useTranslations("orgEvents");
  const locale = useLocale();
  const titleId = `event-${event.id}-title`;
  return (
    <Row
      aria-labelledby={titleId}
      data-org-event={event.id}
      data-status={event.status}
      title={event.title}
      titleId={titleId}
      href={href}
      meta={
        <span className="flex flex-wrap gap-x-4">
          <span className="tabular-nums">{t("when", { day: eventDay(locale, event.starts_at), time: formatTime(locale, event.starts_at) })}</span>
          <span>{event.online ? t("online") : (event.county_name ?? event.venue)}</span>
        </span>
      }
      badges={[
        <Chip key="status" kind={EVENT_CHIP[event.status]}>
          {t(`status.${event.status}`)}
        </Chip>,
      ]}
    />
  );
}
