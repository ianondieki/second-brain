import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { AuthShell } from "@/components/AuthShell";
import { ClientStrings } from "@/components/ClientStrings";
import { IntlScope } from "@/components/IntlScope";
import { PageHeader } from "@/components/ui/PageHeader";
import { getSignedIn } from "@/lib/api/server";
import { homeOf } from "@/lib/auth/routing";
import { clientStrings } from "@/lib/i18n/client-strings";
import { returnPathParam } from "@/lib/return-path";

import { LoginForm } from "./LoginForm";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("login");
  return { title: t("title") };
}

/**
 * Log in. `?next=` (set by the proxy for a signed-out visit to a signed-in page) is the page to return to, kept only
 * when it is one of this site's signed-in pages written plainly (lib/return-path.ts). A person already signed in goes
 * there, or to their own home, with a server-side redirect (P16-B review MINOR 3).
 */
export default async function LoginPage({ searchParams }: PageProps<"/login">) {
  const next = returnPathParam((await searchParams).next);
  const me = await getSignedIn();
  if (me) redirect(next ?? homeOf(me));
  const t = await getTranslations("login");
  return (
    <AuthShell>
      <PageHeader title={t("title")} lead={t("lead")} />
      <IntlScope namespaces={["login", "fields", "validation", "errors"]}>
        {/* The password field's show/hide words are server-formatted (components/ui/PasswordField.tsx). */}
        <ClientStrings strings={await clientStrings(["fields"])}>
          <LoginForm next={next} />
        </ClientStrings>
      </IntlScope>
    </AuthShell>
  );
}
