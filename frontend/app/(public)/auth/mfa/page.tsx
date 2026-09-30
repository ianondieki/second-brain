import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { AuthShell } from "@/components/AuthShell";
import { IntlScope } from "@/components/IntlScope";
import { SignOutButton } from "@/components/SignOutButton";
import { PageHeader } from "@/components/ui/PageHeader";
import { requirePendingMfa } from "@/lib/api/server";
import { returnPathParam } from "@/lib/return-path";

import { MfaForm } from "./MfaForm";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("mfa");
  return { title: t("title") };
}

/** The second factor; `?next=` (from /login) is the page to return to afterwards (lib/return-path.ts). */
export default async function MfaPage({ searchParams }: PageProps<"/auth/mfa">) {
  const next = returnPathParam((await searchParams).next);
  await requirePendingMfa(next);
  const t = await getTranslations("mfa");
  return (
    // No phone and no recovery codes: "Sign out" is the way out of a half-finished sign-in.
    <AuthShell topBarAction={<SignOutButton />}>
      <PageHeader title={t("title")} />
      <IntlScope namespaces={["mfa", "validation", "errors"]}>
        <MfaForm next={next} />
      </IntlScope>
    </AuthShell>
  );
}
