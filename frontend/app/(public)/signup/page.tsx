import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { AuthShell } from "@/components/AuthShell";
import { IntlScope } from "@/components/IntlScope";
import { PageHeader } from "@/components/ui/PageHeader";
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
      <PageHeader title={t("title")} lead={t("lead")} />
      <IntlScope namespaces={["signup", "fields", "validation", "errors", "orgKind"]}>
        <SignupForm initialConsents={consents} />
      </IntlScope>
    </AuthShell>
  );
}
