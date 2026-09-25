import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { AuthShell } from "@/components/AuthShell";

import { SignupForm } from "./SignupForm";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("signup");
  return { title: t("title") };
}

export default async function SignupPage() {
  const t = await getTranslations("signup");
  return (
    <AuthShell>
      <h1 className="text-xl text-ink lg:text-2xl">{t("title")}</h1>
      <p className="mt-3 text-ink-soft">{t("lead")}</p>
      <SignupForm />
    </AuthShell>
  );
}
