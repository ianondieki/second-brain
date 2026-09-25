import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { AuthShell } from "@/components/AuthShell";

import { CheckEmail } from "./CheckEmail";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("checkEmail");
  return { title: t("title") };
}

/** After signup, and after "Email me a sign-in link" (`?for=login`). */
export default async function CheckEmailPage({ searchParams }: PageProps<"/signup/check-email">) {
  const t = await getTranslations("checkEmail");
  const kind = (await searchParams).for === "login" ? "login" : "signup";
  return (
    <AuthShell>
      <h1 className="text-xl text-ink lg:text-2xl">{t("title")}</h1>
      <CheckEmail kind={kind} />
    </AuthShell>
  );
}
