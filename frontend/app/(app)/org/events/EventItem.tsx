import { useLocale, useTranslations } from "next-intl";
import type { ReactNode } from "react";

import { EVENT_CHIP } from "@/components/events/status";
import type { EventOut } from "@/components/events/event-draft";
import { eventDay } from "@/components/events/when";
import { Chip } from "@/components/tracker/Chip";
import { ItemCard } from "../ItemCard";
import { formatTime } from "@/lib/format";

/**
 * One of the organisation's events in its list (REQ-DEV-02), a card as the Briefs' under its county's photograph band
 * (the lattice for an online event or a county without one; D-67): the title
 * linking to its page, when (Nairobi) and where on one line, and one status mark (In review, Published, Not approved,
 * Cancelled; docs/spec/07 item 2: at most two).
 */
export function EventItem({ event, href, band }: { event: EventOut; href: string; band?: ReactNode }) {
  const t = useTranslations("orgEvents");
  const locale = useLocale();
  const titleId = `event-${event.id}-title`;
  return (
    <ItemCard
      band={band}
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
      chips={[
        <Chip key="status" kind={EVENT_CHIP[event.status]}>
          {t(`status.${event.status}`)}
        </Chip>,
      ]}
    />
  );
}
