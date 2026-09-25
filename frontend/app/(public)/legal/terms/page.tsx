import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { AuthShell } from "@/components/AuthShell";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("legal");
  return { title: t("termsTitle") };
}

// Placeholder until the advocate-reviewed terms arrive at G2 (GATES.md); agents never write legal text.
export default async function TermsPage() {
  const t = await getTranslations("legal");
  return (
    <AuthShell>
      <h1 className="text-xl text-ink lg:text-2xl">{t("termsTitle")}</h1>
      <p className="mt-4 text-ink-soft">{t("termsBody")}</p>
    </AuthShell>
  );
}
