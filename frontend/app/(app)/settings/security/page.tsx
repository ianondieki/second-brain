import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { IntlScope } from "@/components/IntlScope";
import { SignedInShell } from "@/components/SignedInShell";
import { requireMe } from "@/lib/api/server";
import { homeFor } from "@/lib/auth/routing";

import { PasswordSettings } from "./PasswordSettings";
import { SecuritySettings } from "./SecuritySettings";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("security");
  return { title: t("pageTitle") };
}

/** Sign-in security: two-step sign-in first (the page's one primary action), then the password. */
export default async function SecurityPage() {
  const me = await requireMe();
  const t = await getTranslations("security");
  const home = homeFor(me.side);
  return (
    <SignedInShell homeHref={home}>
      <h1 className="text-xl text-ink lg:text-2xl">{t("pageTitle")}</h1>
      <IntlScope namespaces={["security", "password", "signup", "fields", "validation", "errors"]}>
        <section aria-labelledby="two-step-heading" className="mt-8">
          <h2 id="two-step-heading" className="text-lg text-ink">
            {t("title")}
          </h2>
          <p className="mt-2 text-ink-soft">{t("lead")}</p>
          <SecuritySettings
            enrolled={me.mfa.enrolled}
            required={me.mfa.required}
            homeHref={home}
            email={me.user.email}
            passwordSet={me.user.password_set}
          />
        </section>
        <PasswordSettings email={me.user.email} passwordSet={me.user.password_set} />
      </IntlScope>
    </SignedInShell>
  );
}
