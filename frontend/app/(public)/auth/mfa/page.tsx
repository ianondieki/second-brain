import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { AuthShell } from "@/components/AuthShell";
import { requirePendingMfa } from "@/lib/api/server";

import { MfaForm } from "./MfaForm";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("mfa");
  return { title: t("title") };
}

export default async function MfaPage() {
  await requirePendingMfa();
  const t = await getTranslations("mfa");
  return (
    <AuthShell>
      <h1 className="text-xl text-ink lg:text-2xl">{t("title")}</h1>
      <p className="mt-3 text-ink-soft">{t("lead")}</p>
      <MfaForm />
    </AuthShell>
  );
}
