import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { HomeSummary } from "@/components/HomeSummary";
import { SignedInShell } from "@/components/SignedInShell";
import { requireMe } from "@/lib/api/server";
import { homeFor } from "@/lib/auth/routing";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("home");
  return { title: t("orgPageTitle") };
}

/** Organisation home, Phase 1 placeholder: owners without two-step sign-in are asked to turn it on. */
export default async function OrganisationHome() {
  const me = await requireMe();
  const home = homeFor(me.side);
  if (home !== "/org") redirect(home);
  const t = await getTranslations("home");
  const org = me.memberships[0]?.org_name;
  return (
    <SignedInShell homeHref={home}>
      <HomeSummary me={me} lead={org ? t("orgLead", { org }) : t("orgLeadNoName")} />
    </SignedInShell>
  );
}
