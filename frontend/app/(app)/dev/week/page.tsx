import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { getLocale, getTranslations } from "next-intl/server";

import { DevNav } from "@/components/DevNav";
import { SignedInShell } from "@/components/SignedInShell";
import { PageHeader } from "@/components/ui/PageHeader";
import { RowList } from "@/components/ui/RowList";
import { Section } from "@/components/ui/Section";
import { requireMe } from "@/lib/api/server";
import { homeFor } from "@/lib/auth/routing";

import { trendOfTheDay, weekEvents } from "./data";
import { EventRow } from "./EventRow";
import { TrendRow } from "./TrendRow";
import { byDay, longDay } from "./week";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("week");
  return { title: t("page.pageTitle") };
}

/**
 * Developer › This week (REQ-DEV-02; D-60, D-61): every published event of this week and next in the developer's
 * county or online, grouped by Nairobi day, soonest first, then the trend of the day. Reached from Home's strip (no
 * nav item of its own: the developer nav stays at five, principle 6). Nothing at all: one sentence, nothing else.
 * Developers only; organisations go to their own home, as from every developer route.
 */
export default async function WeekPage() {
  const me = await requireMe();
  const home = homeFor(me.side);
  if (home !== "/dev") redirect(home);
  const [t, locale, events, trend] = await Promise.all([getTranslations("week"), getLocale(), weekEvents(), trendOfTheDay()]);
  const days = byDay(events.items);

  return (
    <SignedInShell homeHref="/dev" nav={<DevNav current="home" />} wide>
      <div className="flex max-w-3xl flex-col gap-12 lg:gap-14">
        <PageHeader back={{ href: "/dev", label: t("page.back") }} title={t("page.title")} lead={t("page.lead")} />

        {/* No event: one sentence (the trend of the day, when there is one, still follows). */}
        {days.length === 0 ? (
          <p className="-mt-4 text-ink" data-week-empty="">
            {t("page.empty")}
          </p>
        ) : null}

        {days.map((group) => (
          <Section
            key={group.day}
            title={longDay(locale, group.first)}
            headingId={`week-${group.day}`}
            description={t("page.dayCount", { count: group.events.length })}
            data-week-day={group.day}
          >
            <div className="rounded-panel border border-line bg-field px-4 sm:px-6">
              <RowList rule={false}>
                {group.events.map((event) => (
                  <EventRow key={event.id} event={event} showDay={false} />
                ))}
              </RowList>
            </div>
          </Section>
        ))}

        {trend ? (
          <Section title={t("page.trendHeading")} headingId="week-trend">
            <div className="rounded-panel border border-line bg-field px-4 sm:px-6">
              <RowList rule={false}>
                <TrendRow trend={trend} />
              </RowList>
            </div>
          </Section>
        ) : null}
      </div>
    </SignedInShell>
  );
}
