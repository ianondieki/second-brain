import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import { DevNav } from "@/components/DevNav";
import { SignedInShell } from "@/components/SignedInShell";
import { standaloneLinkClass } from "@/components/ui/Button";
import { requireMe } from "@/lib/api/server";
import { homeFor } from "@/lib/auth/routing";

import { getOrgCard } from "../directory";
import { Empty } from "../DirectoryResults";
import { filtersHref, parseFilters } from "../filters";
import { VerificationBadge } from "../VerificationBadge";

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
          <p className="-mt-2 mb-4">
            <Link href={back} className={standaloneLinkClass}>
              {t("detailBack")}
            </Link>
          </p>
          <h1 className="text-xl [overflow-wrap:anywhere] text-ink lg:text-2xl">{org.name}</h1>
          <VerificationBadge badge={org.badge} className="mt-3 text-base" />
          <dl className="mt-8 grid gap-x-8 gap-y-4 border-t border-line pt-6 sm:grid-cols-[minmax(9rem,auto)_1fr]">
            <Row label={t("detailType")}>{kinds(org.kind)}</Row>
            <Row label={t("detailCounty")}>{org.county?.name ?? t("detailNone")}</Row>
            <Row label={t("detailNiches")}>
              {org.niches.length > 0 ? (
                <ul className="flex flex-col gap-1">
                  {org.niches.map((niche) => (
                    <li key={niche.id}>{niche.label}</li>
                  ))}
                </ul>
              ) : (
                t("detailNone")
              )}
            </Row>
            {org.responsiveness ? <Row label={t("detailResponse")}>{org.responsiveness.text}</Row> : null}
          </dl>
        </>
      ) : (
        <>
          <h1 className="text-xl text-ink lg:text-2xl">{t("title")}</h1>
          <div className="mt-6">
            <Empty sentence={t("notFound")} action={t("detailBack")} href={back} />
          </div>
        </>
      )}
    </SignedInShell>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5 sm:contents">
      <dt className="text-sm font-medium text-ink-soft sm:pt-0.5">{label}</dt>
      <dd className="min-w-0 text-ink">{children}</dd>
    </div>
  );
}
