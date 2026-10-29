import { getLocale, getTranslations } from "next-intl/server";

import { safeHttpsUrl } from "@/components/problem/problem";
import { Card } from "@/components/ui/Card";
import { Description, DescriptionList } from "@/components/ui/DescriptionList";
import { formatTime } from "@/lib/format";

import type { EventOut } from "./event-draft";
import { eventDay, nairobiDate } from "./when";

/**
 * An event's details as its organisation and staff read them (REQ-DEV-02): when in Nairobi, where (the venue and
 * county, or online with the join address), the organiser, its own page and the description as plain paragraphs, on
 * one flat sheet. Addresses are shown as text with a link only when they are plain https.
 */
export async function EventDetails({ event, organiser }: { event: EventOut; organiser?: string }) {
  const [t, locale] = await Promise.all([getTranslations("orgEvents"), getLocale()]);
  const when = (iso: string) => t("when", { day: eventDay(locale, iso), time: formatTime(locale, iso) });
  const sameDay = nairobiDate(event.starts_at) === nairobiDate(event.ends_at);
  const end = sameDay ? formatTime(locale, event.ends_at) : when(event.ends_at);
  const none = <span className="text-ink-soft">{t("facts.none")}</span>;
  const address = (url: string | null) => {
    if (!url) return none;
    const href = safeHttpsUrl(url);
    if (!href) return <span className="[overflow-wrap:anywhere]">{url}</span>;
    return (
      <a href={href} target="_blank" rel="noopener noreferrer" className="font-semibold [overflow-wrap:anywhere] text-accent underline decoration-1 hover:decoration-2">
        {url}
        <span className="sr-only"> {t("newTab")}</span>
      </a>
    );
  };
  return (
    <Card as="section" variant="flat" aria-labelledby="event-details" data-event-details="">
      <h2 id="event-details" className="sr-only">
        {t("facts.heading")}
      </h2>
      <DescriptionList figures>
        <Description label={t("facts.when")}>
          <span className="font-semibold">{t("range", { start: when(event.starts_at), end })}</span>
        </Description>
        <Description label={t("facts.where")}>
          {event.online ? (
            <span className="flex flex-col items-start gap-1">
              <span className="font-semibold">{t("online")}</span>
              {address(event.join_url)}
            </span>
          ) : (
            <span className="font-semibold">
              {event.venue && event.county_name ? t("venue", { venue: event.venue, county: event.county_name }) : (event.venue ?? event.county_name)}
            </span>
          )}
        </Description>
        <Description label={t("facts.organiser")}>{organiser ?? event.organiser ?? none}</Description>
        <Description label={t("facts.link")}>{address(event.link)}</Description>
        <Description label={t("facts.description")}>
          <span className="flex max-w-[65ch] flex-col gap-3">
            {event.description
              .split(/\n\s*\n/)
              .map((part) => part.trim())
              .filter(Boolean)
              .map((text, index) => (
                <span key={index} className="block whitespace-pre-line">
                  {text}
                </span>
              ))}
          </span>
        </Description>
      </DescriptionList>
    </Card>
  );
}
