import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { IntlScope } from "@/components/IntlScope";
import { SignedInShell } from "@/components/SignedInShell";
import { PageHeader } from "@/components/ui/PageHeader";
import { Section } from "@/components/ui/Section";
import { requireMe } from "@/lib/api/server";
import { homeOf } from "@/lib/auth/routing";

import { SettingsTabs } from "../SettingsTabs";
import { PasswordSettings } from "./PasswordSettings";
import { PasswordStateProvider } from "./PasswordState";
import { SecuritySettings } from "./SecuritySettings";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("security");
  return { title: t("pageTitle") };
}

/**
 * Sign-in security: two-step sign-in first (the page's one primary action), then the password. The page is within a
 * few hundred bytes of the 150 KB JS budget (docs/spec/07 item 5): its client parts write out the Section and Badge
 * markup instead of importing them (as ErrorScreen does for its button); the server parts compose the system.
 */
export default async function SecurityPage() {
  const me = await requireMe();
  const t = await getTranslations("security");
  const tApp = await getTranslations("app");
  const home = homeOf(me);
  return (
    <SignedInShell homeHref={home}>
      <SettingsTabs current="security" />
      <PageHeader title={t("pageTitle")} />
      <IntlScope namespaces={["security", "password", "signup", "fields", "validation", "errors"]}>
        <PasswordStateProvider initial={me.user.password_set}>
          <Section title={t("title")} headingId="two-step-heading" description={t("lead")} className="mt-10">
            <SecuritySettings
              enrolled={me.mfa.enrolled}
              required={me.mfa.required}
              homeHref={home}
              email={me.user.email}
              productName={tApp("name")}
            />
          </Section>
          <PasswordSettings email={me.user.email} />
        </PasswordStateProvider>
      </IntlScope>
    </SignedInShell>
  );
}
