import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { DevNav } from "@/components/DevNav";
import { SignedInShell } from "@/components/SignedInShell";
import { Description, DescriptionList } from "@/components/ui/DescriptionList";
import { EmptyState } from "@/components/ui/EmptyState";
import { Avatar } from "@/components/ui/Avatar";
import { NicheBand } from "@/components/ui/NicheBand";
import { PageHeader } from "@/components/ui/PageHeader";
import { requireMe } from "@/lib/api/server";
import { homeFor } from "@/lib/auth/routing";

import { getOrgCard } from "../directory";
import { filtersHref, parseFilters } from "../filters";
import { VerificationBadge } from "../VerificationBadge";
import { Card } from "@/components/ui/Card";

export async function generateMetadata({ params }: PageProps<"/dev/companies/[orgId]">): Promise<Metadata> {
  const t = await getTranslations("companies");
  const org = await getOrgCard((await params).orgId).catch(() => null);
  return { title: org?.name ?? t("pageTitle") };
}

/**
 * One organisation from the directory (GET /api/directory/orgs/{org_id}): badge, org type, county, every niche it is
 * listed under, and its response record when the API sends one. Unknown, unlisted and delisted ids read the same.
 */
export default async function OrganisationPage({ params, searchParams }: PageProps<"/dev/companies/[orgId]">) {
  const me = await requireMe();
  const home = homeFor(me.side);
  if (home !== "/dev") redirect(home);
  const t = await getTranslations("companies");
  const kinds = await getTranslations("orgKind");
  const org = await getOrgCard((await params).orgId);
  // Back to the list this page was opened from: same search, filters and page.
  const back = filtersHref(parseFilters(await searchParams));

  return (
    <SignedInShell homeHref={home} nav={<DevNav current="companies" />}>
      {org ? (
        <>
          <PageHeader
            back={{ href: back, label: t("detailBack") }}
            title={
              <span className="flex items-center gap-4">
                <Avatar name={org.name} kind="org" size="lg" />
                <span className="min-w-0">{org.name}</span>
              </span>
            }
          >
            <p className="mt-3">
              <VerificationBadge badge={org.badge} />
            </p>
          </PageHeader>
          {/* The facts as one white card on the canvas, opening with the HQ county's photograph and its name (P25;
              decorative, the county is named on it and in the facts; never a logo). */}
          <Card variant="flat" padding="none" className="mt-8 overflow-hidden">
            {org.county ? (
              <NicheBand county={org.county.code} className="h-24 rounded-none sm:h-28" sizes="(min-width: 640px) 36rem, 100vw" wide>
                <span className="font-display text-lg font-semibold">{org.county.name}</span>
              </NicheBand>
            ) : null}
            <div className="p-5 sm:p-6">
          <DescriptionList>
            <Description label={t("detailType")}>{kinds(org.kind)}</Description>
            <Description label={t("detailCounty")}>{org.county?.name ?? t("detailNone")}</Description>
            <Description label={t("detailNiches")}>
              {org.niches.length > 0 ? (
                <ul className="flex flex-col gap-1">
                  {org.niches.map((niche) => (
                    <li key={niche.id}>{niche.label}</li>
                  ))}
                </ul>
              ) : (
                t("detailNone")
              )}
            </Description>
            {org.responsiveness ? (
              <Description label={t("detailResponse")}>{org.responsiveness.text}</Description>
            ) : null}
          </DescriptionList>
            </div>
          </Card>
        </>
      ) : (
        <>
          <PageHeader title={t("title")} />
          <EmptyState sentence={t("notFound")} action={t("detailBack")} href={back} className="mt-8" />
        </>
      )}
    </SignedInShell>
  );
}
