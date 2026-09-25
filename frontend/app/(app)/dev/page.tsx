import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { HomeSummary } from "@/components/HomeSummary";
import { SignedInShell } from "@/components/SignedInShell";
import { requireMe } from "@/lib/api/server";
import { homeFor } from "@/lib/auth/routing";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("home");
  return { title: t("devPageTitle") };
}

/** Developer home, Phase 1 placeholder. */
export default async function DeveloperHome() {
  const me = await requireMe();
  const home = homeFor(me.side);
  if (home !== "/dev") redirect(home);
  const t = await getTranslations("home");
  return (
    <SignedInShell homeHref={home}>
      <HomeSummary me={me} lead={t("devLead")} />
    </SignedInShell>
  );
}
