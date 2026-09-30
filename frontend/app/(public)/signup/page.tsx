import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { AuthShell } from "@/components/AuthShell";
import { ClientStrings } from "@/components/ClientStrings";
import { IntlScope } from "@/components/IntlScope";
import { PageHeader } from "@/components/ui/PageHeader";
import { getSignedIn, getSignupConsents } from "@/lib/api/server";
import { homeOf } from "@/lib/auth/routing";
import { clientStrings } from "@/lib/i18n/client-strings";

import { SignupForm } from "./SignupForm";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("signup");
  return { title: t("title") };
}

/** Sign up; a person already signed in goes to their own home (a server-side redirect, like / and /login). */
export default async function SignupPage() {
  const me = await getSignedIn();
  if (me) redirect(homeOf(me));
  const [t, consents] = await Promise.all([getTranslations("signup"), getSignupConsents()]);
  return (
    <AuthShell>
      <PageHeader title={t("title")} lead={t("lead")} />
      <IntlScope namespaces={["signup", "fields", "validation", "errors", "orgKind"]}>
        {/* The password field's show/hide words are server-formatted (components/ui/PasswordField.tsx). */}
        <ClientStrings strings={await clientStrings(["fields"])}>
          <SignupForm initialConsents={consents} />
        </ClientStrings>
      </IntlScope>
    </AuthShell>
  );
}
