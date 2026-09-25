import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { SignedInShell } from "@/components/SignedInShell";
import { requireMe } from "@/lib/api/server";
import { homeFor } from "@/lib/auth/routing";

import { SecuritySettings } from "./SecuritySettings";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("security");
  return { title: t("title") };
}

export default async function SecurityPage() {
  const me = await requireMe();
  const t = await getTranslations("security");
  const home = homeFor(me.side);
  return (
    <SignedInShell homeHref={home}>
      <h1 className="text-xl text-ink lg:text-2xl">{t("title")}</h1>
      <p className="mt-3 text-ink-soft">{t("lead")}</p>
      <SecuritySettings enrolled={me.mfa.enrolled} required={me.mfa.required} homeHref={home} />
    </SignedInShell>
  );
}
