import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { ClientStrings } from "@/components/ClientStrings";
import { PortalNavFor } from "@/components/PortalNavFor";
import { SignedInShell } from "@/components/SignedInShell";
import { PageHeader } from "@/components/ui/PageHeader";
import { Card } from "@/components/ui/Card";
import { Section } from "@/components/ui/Section";
import { requireMe } from "@/lib/api/server";
import { homeOf } from "@/lib/auth/routing";
import { clientStrings, pickedStrings } from "@/lib/i18n/client-strings";

import { SettingsTabs } from "../SettingsTabs";
import { PasswordSettings } from "./PasswordSettings";
import { PasswordStateProvider } from "./PasswordState";
import { SecuritySettings } from "./SecuritySettings";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("security");
  return { title: t("pageTitle") };
}

/**
 * Sign-in security: two-step sign-in first (the page's one primary action), then the password. The page is close to
 * the 150 KB JS budget (docs/spec/07 item 5; 146,820 bytes in P16-D): its client parts read server-formatted strings
 * instead of next-intl's client runtime, and write out the Section and Badge markup instead of importing them (as
 * ErrorScreen does for its button); the server parts compose the system.
 */
export default async function SecurityPage() {
  const me = await requireMe();
  const t = await getTranslations("security");
  const tApp = await getTranslations("app");
  const home = homeOf(me);
  const tNav = await getTranslations("settingsNav");
  return (
    <SignedInShell homeHref={home} nav={<PortalNavFor me={me} />} wide>
      <PageHeader title={tNav("label")} back={{ href: home, label: t("back") }} />
      <SettingsTabs current="security" />
      {/* Server-formatted strings, not next-intl's client runtime (about 3.5 KB of the budget; P16-D). */}
      <ClientStrings
        strings={{
          ...(await clientStrings(["security", "password", "fields", "validation", "errors"])),
          ...(await pickedStrings("signup", ["passwordHint"])),
        }}
      >
        <PasswordStateProvider initial={me.user.password_set}>
          <div className="mt-10 flex max-w-3xl flex-col gap-6">
            <Card variant="flat" className="p-5 sm:p-6">
              <Section title={t("title")} headingId="two-step-heading" description={t("lead")} headingStyle="card">
                <SecuritySettings
                  enrolled={me.mfa.enrolled}
                  required={me.mfa.required}
                  homeHref={home}
                  email={me.user.email}
                  productName={tApp("name")}
                />
              </Section>
            </Card>
            <Card variant="flat" className="p-5 sm:p-6">
              <PasswordSettings email={me.user.email} />
            </Card>
          </div>
        </PasswordStateProvider>
      </ClientStrings>
    </SignedInShell>
  );
}
