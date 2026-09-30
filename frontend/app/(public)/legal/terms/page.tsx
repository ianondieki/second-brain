import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { AuthShell } from "@/components/AuthShell";
import { PageHeader } from "@/components/ui/PageHeader";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("legal");
  return { title: t("termsTitle") };
}

// Placeholder until the advocate-reviewed terms arrive at G2 (GATES.md); agents never write legal text.
export default async function TermsPage() {
  const t = await getTranslations("legal");
  return (
    <AuthShell>
      <PageHeader title={t("termsTitle")} lead={t("termsBody")} />
    </AuthShell>
  );
}
