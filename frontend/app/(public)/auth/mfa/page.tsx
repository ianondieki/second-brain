import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { AuthShell } from "@/components/AuthShell";
import { IntlScope } from "@/components/IntlScope";
import { SignOutButton } from "@/components/SignOutButton";
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
    // No phone and no recovery codes: "Sign out" is the way out of a half-finished sign-in.
    <AuthShell topBarAction={<SignOutButton />}>
      <h1 className="text-xl text-ink lg:text-2xl">{t("title")}</h1>
      <IntlScope namespaces={["mfa", "validation", "errors"]}>
        <MfaForm />
      </IntlScope>
    </AuthShell>
  );
}
