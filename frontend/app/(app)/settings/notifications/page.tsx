import type { Metadata } from "next";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { getLocale, getTranslations } from "next-intl/server";

import { ClientStrings } from "@/components/ClientStrings";
import { PortalNavFor } from "@/components/PortalNavFor";
import { Section } from "@/components/ui/Section";
import { SignedInShell } from "@/components/SignedInShell";
import { forwardHeaders, requireMe, serverApi } from "@/lib/api/server";
import { homeOf } from "@/lib/auth/routing";
import { formatMoment } from "@/lib/format";
import { DATA_SAVER_COOKIE } from "@/lib/data-saver";
import { clientStrings, pickedStrings } from "@/lib/i18n/client-strings";

import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { BackLink } from "@/components/ui/BackLink";
import { PageHero } from "@/components/ui/PageHero";

import { pickMembership } from "../../org/membership";
import { OrgPicker } from "../../org/OrgPicker";
import { DataSaverSwitch } from "../profile/DataSaverSwitch";
import { SettingsTabs } from "../SettingsTabs";
import { notificationChoices, preferenceChoices, type ConsentItem } from "./choices";
import { CalendarFeed } from "./CalendarFeed";
import { feedStatus } from "./feed-data";
import { NotificationChoices } from "./NotificationChoices";
import { myPreferences } from "./preferences-data";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("notificationSettings");
  return { title: t("pageTitle") };
}

/** The signed-in person's consents (GET /api/me/consents), bounded so a hung API ends in the route's error page. */
async function myConsents(): Promise<ConsentItem[]> {
  const { data, response } = await serverApi().GET("/api/me/consents", {
    headers: await forwardHeaders(),
    signal: AbortSignal.timeout(5000),
    cache: "no-store",
  });
  if (response.status === 401) redirect("/login"); // the session ended between the page's /me check and this call
  if (!data) throw new Error(`GET /api/me/consents answered ${response.status}`);
  return data;
}

/**
 * Notification settings (docs/spec/07 item 1, the avatar menu; every email footer's "Manage notifications"): the
 * consents that decide which messages are sent, for anyone signed in, on either side (REQ-CON-01, REQ-NOT-03), and
 * the notification preferences beside them in their channel's group (REQ-NOT-06; P21: the saved-search digest). Then
 * "Data": the data-saver switch (P27, REQ-UX-08), the same one developers also have on Profile, here for both sides; it
 * acts at once on this device and is not part of "Save choices".
 */
export default async function NotificationSettingsPage({ searchParams }: PageProps<"/settings/notifications">) {
  const me = await requireMe();
  const home = homeOf(me);
  const t = await getTranslations("notificationSettings");
  const tf = await getTranslations("calendarFeed");
  // The calendar feed is the person's own, or, for an organisation member, the chosen organisation's (?org=).
  const picked = me.side === "org" ? pickMembership(me.memberships, (await searchParams).org) : null;
  const feedOrg = picked?.kind === "member" ? picked.membership : null;
  const [consents, preferenceItems, jar, feed, locale] = await Promise.all([
    myConsents(),
    myPreferences(),
    cookies(),
    me.side === "org" && !feedOrg ? Promise.resolve(null) : feedStatus(feedOrg?.org_id),
    getLocale(),
  ]);
  const choices = notificationChoices(consents);
  // A kind the page has words for reads in the page's language; any other keeps the API's own label.
  const preferences = preferenceChoices(preferenceItems, (item) =>
    t.has(`preference.${item.kind}` as "preference.saved_search_digest")
      ? t(`preference.${item.kind}` as "preference.saved_search_digest")
      : item.label,
  );
  const tNav = await getTranslations("settingsNav");
  return (
    <SignedInShell homeHref={home} nav={<PortalNavFor me={me} />} wide>
      {/* One 48 rem column: the tab strip ends where the card ends. */}
      <div className="max-w-3xl">
        <BackLink href={home}>{(await getTranslations("security"))("back")}</BackLink>
        <PageHero
          eyebrow={(await getTranslations("portal"))("eyebrow.settings")}
          title={tNav("label")}
          lead={(await getTranslations("portal"))("settings.leadNotifications")}
          tabs={<SettingsTabs current="notifications" developer={me.side === "developer"} />}
        />
        <div>
          {choices.length === 0 && preferences.length === 0 ? (
            <EmptyState sentence={t("empty")} action={t("action.home")} href={home} />
          ) : (
            <Card variant="flat" className="p-5 sm:p-6">
              <Section
                title={t("pageTitle")}
                headingId="notifications-heading"
                description={t("lead")}
                headingStyle="card"
              >
                <ClientStrings strings={await clientStrings(["notificationSettings"])}>
                  <NotificationChoices initial={choices} preferences={preferences} />
                </ClientStrings>
              </Section>
            </Card>
          )}
          {me.side !== "org" || feedOrg ? (
            <Card variant="flat" className="mt-6 p-5 sm:p-6" data-calendar-feed-card="">
              <Section
                title={tf("title")}
                headingId="calendar-feed-heading"
                headingStyle="card"
                description={tf("lead")}
              >
                <div className="flex flex-col gap-4">
                  {feedOrg && me.memberships.length > 1 ? (
                    <OrgPicker
                      memberships={me.memberships}
                      current={feedOrg.org_id}
                      action="/settings/notifications"
                    />
                  ) : null}
                  {feedOrg ? <p className="text-ink">{tf("forOrg", { org: feedOrg.org_name })}</p> : null}
                  <p className="max-w-[62ch] text-sm text-ink-soft" data-feed-private="">
                    {tf("private")}
                  </p>
                  <ClientStrings strings={await clientStrings(["calendarFeed"])}>
                    <CalendarFeed
                      initial={feed?.active ? "live" : "none"}
                      orgId={feedOrg?.org_id}
                      lastRead={feed?.last_fetched_at ? formatMoment(locale, feed.last_fetched_at) : null}
                    />
                  </ClientStrings>
                </div>
              </Section>
            </Card>
          ) : null}
          <Card variant="flat" className="mt-6 p-5 sm:p-6" data-data-saver-card="">
            <Section title={t("dataTitle")} headingId="data-heading" headingStyle="card">
              <ClientStrings
                strings={await pickedStrings("profileSettings", ["dataSaver", "dataSaverExplain", "on", "off"])}
              >
                <DataSaverSwitch initial={jar.get(DATA_SAVER_COOKIE)?.value === "1"} />
              </ClientStrings>
            </Section>
          </Card>
        </div>
      </div>
    </SignedInShell>
  );
}
