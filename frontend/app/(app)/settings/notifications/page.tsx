import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { ClientStrings } from "@/components/ClientStrings";
import { PortalNavFor } from "@/components/PortalNavFor";
import { Section } from "@/components/ui/Section";
import { SignedInShell } from "@/components/SignedInShell";
import { forwardHeaders, requireMe, serverApi } from "@/lib/api/server";
import { homeOf } from "@/lib/auth/routing";
import { clientStrings } from "@/lib/i18n/client-strings";

import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";

import { SettingsTabs } from "../SettingsTabs";
import { notificationChoices, type ConsentItem } from "./choices";
import { NotificationChoices } from "./NotificationChoices";

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
 * consents that decide which messages are sent, for anyone signed in, on either side (REQ-CON-01, REQ-NOT-03).
 */
export default async function NotificationSettingsPage() {
  const me = await requireMe();
  const home = homeOf(me);
  const t = await getTranslations("notificationSettings");
  const choices = notificationChoices(await myConsents());
  const [tNav, tSecurity] = await Promise.all([getTranslations("settingsNav"), getTranslations("security")]);
  return (
    <SignedInShell homeHref={home} nav={<PortalNavFor me={me} />} wide>
      <PageHeader title={tNav("label")} back={{ href: home, label: tSecurity("back") }} />
      <SettingsTabs current="notifications" />
      <div className="mt-10">
        {choices.length === 0 ? (
          <EmptyState sentence={t("empty")} action={t("action.home")} href={home} />
        ) : (
          <Card variant="flat" className="max-w-3xl p-5 sm:p-6">
            <Section title={t("pageTitle")} headingId="notifications-heading" description={t("lead")} headingStyle="card">
              <ClientStrings strings={await clientStrings(["notificationSettings"])}>
                <NotificationChoices initial={choices} />
              </ClientStrings>
            </Section>
          </Card>
        )}
      </div>
    </SignedInShell>
  );
}
