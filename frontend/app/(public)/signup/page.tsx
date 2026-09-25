import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { AuthShell } from "@/components/AuthShell";
import { getSignupConsents } from "@/lib/api/server";

import { SignupForm } from "./SignupForm";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("signup");
  return { title: t("title") };
}

export default async function SignupPage() {
  const [t, consents] = await Promise.all([getTranslations("signup"), getSignupConsents()]);
  return (
    <AuthShell>
      <h1 className="text-xl text-ink lg:text-2xl">{t("title")}</h1>
      <p className="mt-3 text-ink-soft">{t("lead")}</p>
      <SignupForm initialConsents={consents} />
    </AuthShell>
  );
}
