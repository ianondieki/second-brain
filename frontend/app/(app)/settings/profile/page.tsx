import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { myBlocks, myProfile } from "@/app/(app)/dev/teams/data";
import { ClientStrings } from "@/components/ClientStrings";
import { PortalNavFor } from "@/components/PortalNavFor";
import { getCountyNames } from "@/components/problem/data";
import { SignedInShell } from "@/components/SignedInShell";
import { Card } from "@/components/ui/Card";
import { PageHero } from "@/components/ui/PageHero";
import { Section } from "@/components/ui/Section";
import { requireMe } from "@/lib/api/server";
import { homeOf } from "@/lib/auth/routing";
import { clientStrings } from "@/lib/i18n/client-strings";

import { SettingsTabs } from "../SettingsTabs";
import { BlockedList } from "./BlockedList";
import { ProfileForm } from "./ProfileForm";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("profileSettings");
  return { title: t("pageTitle") };
}

/**
 * Settings › Profile (REQ-DEV-03; D-58), developers only (anyone else goes to Security, the first tab): the headline,
 * the county and "Visible to peers" with its one sentence, kept with "Save" (the one primary action); then the
 * developers the caller blocked, each with "Unblock", when there are any.
 */
export default async function ProfileSettingsPage() {
  const me = await requireMe();
  const home = homeOf(me);
  if (me.side !== "developer") redirect("/settings/security");
  const [t, tNav, profile, blocks, countyNames] = await Promise.all([
    getTranslations("profileSettings"),
    getTranslations("settingsNav"),
    myProfile(),
    myBlocks(),
    getCountyNames(),
  ]);
  const counties = [...countyNames].map(([code, name]) => ({ code, name })).sort((a, b) => a.name.localeCompare(b.name));
  // A county the list could not name still shows as chosen.
  if (profile.county_code && !countyNames.has(profile.county_code)) {
    counties.unshift({ code: profile.county_code, name: profile.county_name ?? profile.county_code });
  }

  return (
    <SignedInShell homeHref={home} nav={<PortalNavFor me={me} />} wide>
      {/* One 48 rem column: the tab strip ends where the cards end. */}
      <div className="max-w-3xl">
        <PageHero
          eyebrow={(await getTranslations("portal"))("eyebrow.settings")}
          title={tNav("label")}
          lead={(await getTranslations("portal"))("settings.leadProfile")}
          tabs={<SettingsTabs current="profile" developer />}
        />
        <ClientStrings strings={await clientStrings(["profileSettings"])}>
          <div className="flex flex-col gap-6">
            <Card variant="flat" className="p-5 sm:p-6">
              <Section title={t("title")} headingId="profile-heading" description={t("lead")} headingStyle="card">
                <ProfileForm initial={profile} counties={counties} />
              </Section>
            </Card>
            {blocks.length > 0 ? (
              <Card variant="flat" className="p-5 sm:p-6">
                <Section title={t("blocked.title")} headingId="blocked-heading" description={t("blocked.lead")} headingStyle="card">
                  <BlockedList initial={blocks} />
                </Section>
              </Card>
            ) : null}
          </div>
        </ClientStrings>
      </div>
    </SignedInShell>
  );
}
