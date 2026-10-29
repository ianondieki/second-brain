import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { DevNav } from "@/components/DevNav";
import { SignedInShell } from "@/components/SignedInShell";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { requireMe } from "@/lib/api/server";
import { homeFor } from "@/lib/auth/routing";

import { getOrgCard } from "../directory";
import { filtersHref, parseFilters } from "../filters";
import { OrgProfile } from "../OrgProfile";

export async function generateMetadata({ params }: PageProps<"/dev/companies/[orgId]">): Promise<Metadata> {
  const t = await getTranslations("companies");
  const org = await getOrgCard((await params).orgId).catch(() => null);
  return { title: org?.name ?? t("pageTitle") };
}

/**
 * One organisation from the directory (GET /api/directory/orgs/{org_id}), drawn by OrgProfile: its place, monogram,
 * name, badge, facts and niches, and the screen's one primary action. Unknown, unlisted and delisted ids read the same.
 */
export default async function OrganisationPage({ params, searchParams }: PageProps<"/dev/companies/[orgId]">) {
  const me = await requireMe();
  const home = homeFor(me.side);
  if (home !== "/dev") redirect(home);
  const t = await getTranslations("companies");
  const org = await getOrgCard((await params).orgId);
  // Back to the list this page was opened from: same search, filters and page.
  const back = filtersHref(parseFilters(await searchParams));

  return (
    <SignedInShell homeHref={home} nav={<DevNav current="companies" />} wide={org !== null}>
      {org ? (
        <OrgProfile org={org} back={back} />
      ) : (
        <>
          <PageHeader title={t("title")} />
          <EmptyState sentence={t("notFound")} action={t("detailBack")} href={back} className="mt-8" />
        </>
      )}
    </SignedInShell>
  );
}
