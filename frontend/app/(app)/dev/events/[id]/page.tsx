import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";
import { getLocale, getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import { DevNav } from "@/components/DevNav";
import { SignedInShell } from "@/components/SignedInShell";
import { standaloneLinkClass } from "@/components/ui/Button";
import { cn } from "@/components/ui/cn";
import { Description, DescriptionList } from "@/components/ui/DescriptionList";
import { PageHeader } from "@/components/ui/PageHeader";
import { Section } from "@/components/ui/Section";
import { requireMe } from "@/lib/api/server";
import { homeFor } from "@/lib/auth/routing";
import { formatTime } from "@/lib/format";

import { emailState, eventPage } from "../../week/data";
import { calendarHref, eventDay, safeHttps, spansDays, WEEK_PATH, NOTIFICATION_SETTINGS_PATH, type EventPage } from "../../week/week";
import { RemindMe } from "./RemindMe";

export async function generateMetadata({ params }: PageProps<"/dev/events/[id]">): Promise<Metadata> {
  const t = await getTranslations("week");
  const me = await requireMe();
  if (homeFor(me.side) !== "/dev") return { title: t("event.pageTitle") };
  const event = await eventPage((await params).id);
  return { title: event.title };
}

/** The description as the poster wrote it: plain text, a paragraph per blank line (never markup). */
function paragraphs(text: string): string[] {
  return text
    .split(/\n\s*\n/)
    .map((part) => part.trim())
    .filter(Boolean);
}

/**
 * Developer › an event (REQ-DEV-02; D-60, D-61): what, when (Nairobi), where (the venue and county, or online with the
 * join link), who organises it; "Remind me" is the page's one primary action, with the line saying what will come;
 * "Add to calendar" as two plain links (the `.ics` file and Google Calendar, both from the API); then the description
 * as plain paragraphs and the event's own page. An event that is not published, cancelled, over or unknown is the
 * not-found page. Developers only; organisations go to their own home, as from every developer route.
 */
export default async function EventPageRoute({ params }: PageProps<"/dev/events/[id]">) {
  const me = await requireMe();
  const home = homeFor(me.side);
  if (home !== "/dev") redirect(home);
  const { id } = await params;
  const [t, locale, event, email] = await Promise.all([getTranslations("week"), getLocale(), eventPage(id), emailState()]);
  const ics = calendarHref(event.calendar_url);
  const google = safeHttps(event.google_calendar_url);
  const join = event.online ? safeHttps(event.join_url) : null;
  const link = safeHttps(event.link);
  const newTab = <span className="sr-only"> {t("event.newTab")}</span>;
  const settings = (chunks: ReactNode) => (
    <Link href={NOTIFICATION_SETTINGS_PATH} className="font-semibold text-accent underline decoration-1 hover:decoration-2">
      {chunks}
    </Link>
  );

  return (
    <SignedInShell homeHref="/dev" nav={<DevNav current="home" />} wide>
      <article aria-labelledby="event-title" className="flex max-w-3xl flex-col gap-12 lg:gap-14" data-event={event.id}>
        <PageHeader back={{ href: WEEK_PATH, label: t("event.back") }} titleId="event-title" title={event.title}>
          <p className="mt-2 text-ink-soft">{t("row.by", { organiser: event.organiser })}</p>
        </PageHeader>

        {/* What the developer acts on: the facts, Remind me and the calendar, on the page's one raised sheet. */}
        <section aria-labelledby="event-when" className="-mt-4 rounded-panel border border-line bg-field p-5 shadow-card sm:p-6">
          <h2 id="event-when" className="sr-only">
            {t("event.when")}
          </h2>
          <DescriptionList>
            <Description label={t("event.when")}>
              <span className="font-semibold tabular-nums" data-event-when="">
                <When event={event} locale={locale} t={t} />
              </span>
              <span className="block text-sm text-ink-soft">{t("event.nairobi")}</span>
            </Description>
          </DescriptionList>

          {/* Remind me right after When: the page's one primary action stays above the fold on a phone. */}
          <div className="mt-5">
            <h3 className="sr-only">{t("reminder.heading")}</h3>
            <RemindMe
              eventId={event.id}
              initial={event.reminder}
              email={email}
              labels={{
                remind: t("reminder.remind"),
                reminding: t("reminder.reminding"),
                decline: t("reminder.decline"),
                declining: t("reminder.declining"),
                set: t("reminder.set"),
                removed: t("reminder.removed"),
                refusal: {
                  gone: t("reminder.refusal.gone"),
                  signedOut: t("reminder.refusal.signedOut"),
                  generic: t("reminder.refusal.generic"),
                },
              }}
              lines={{
                both: t("reminder.line.both"),
                noConsent: t.rich("reminder.line.noConsent", { link: settings }),
                unverified: t("reminder.line.unverified"),
              }}
            />
          </div>

          <DescriptionList className="mt-6 border-t border-line pt-6">
            <Description label={t("event.where")}>
              {event.online ? (
                <span className="flex flex-col items-start">
                  <span className="font-semibold">{t("event.online")}</span>
                  {join ? (
                    <a href={join} target="_blank" rel="noopener noreferrer" className={standaloneLinkClass} data-join="">
                      {t("event.join")}
                      {newTab}
                    </a>
                  ) : null}
                </span>
              ) : (
                <span className="font-semibold">
                  {event.venue && event.county_name
                    ? t("event.venue", { venue: event.venue, county: event.county_name })
                    : (event.venue ?? event.county_name)}
                </span>
              )}
            </Description>
            <Description label={t("event.organiser")}>{event.organiser}</Description>
          </DescriptionList>

          <div className="mt-6 border-t border-line pt-5">
            <h3 className="text-base font-semibold text-ink">{t("event.calendarHeading")}</h3>
            <ul className="mt-1 flex flex-col items-start sm:flex-row sm:gap-8" data-calendar="">
              {ics ? (
                <li>
                  <a href={ics} download className={standaloneLinkClass} data-ics="">
                    {t("event.ics")}
                  </a>
                </li>
              ) : null}
              {google ? (
                <li>
                  <a href={google} target="_blank" rel="noopener noreferrer" className={standaloneLinkClass} data-google="">
                    {t("event.google")}
                    {newTab}
                  </a>
                </li>
              ) : null}
            </ul>
          </div>
        </section>

        <Section title={t("event.about")} headingId="event-about">
          <div className="flex max-w-[65ch] flex-col gap-4 text-ink" data-description="">
            {paragraphs(event.description).map((text, index) => (
              <p key={index} className="[overflow-wrap:anywhere] whitespace-pre-line">
                {text}
              </p>
            ))}
          </div>
          {link ? (
            <p className="mt-4">
              <a href={link} target="_blank" rel="noopener noreferrer" className={cn(standaloneLinkClass, "[overflow-wrap:anywhere]")} data-link="">
                {t("event.link")}
                {newTab}
              </a>
            </p>
          ) : null}
        </Section>
      </article>
    </SignedInShell>
  );
}

/** When, in Nairobi: one day ("Sun 22 Nov, 18:00 to 20:30") or across days ("Sat 21 Nov · 18:00 to Sun 22 Nov · 12:00"). */
function When({ event, locale, t }: { event: EventPage; locale: string; t: Awaited<ReturnType<typeof getTranslations<"week">>> }) {
  const start = formatTime(locale, event.starts_at);
  const end = formatTime(locale, event.ends_at);
  if (!spansDays(event)) return <>{t("event.sameDay", { day: eventDay(locale, event.starts_at), start, end })}</>;
  return (
    <>
      {t("event.range", {
        start: t("row.when", { day: eventDay(locale, event.starts_at), time: start }),
        end: t("row.when", { day: eventDay(locale, event.ends_at), time: end }),
      })}
    </>
  );
}
