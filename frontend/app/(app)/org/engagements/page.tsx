import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { SignedInShell } from "@/components/SignedInShell";
import { orgEngagements } from "@/components/tracker/data";
import { EngagementList } from "@/components/tracker/EngagementList";
import { Refused } from "@/components/tracker/Refused";
import { standaloneLinkClass } from "@/components/ui/Button";
import { requireMe } from "@/lib/api/server";
import { homeFor } from "@/lib/auth/routing";

import { ORG_ENGAGEMENTS_PATH, pickOrg } from "./org";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("tracker");
  return { title: t("pageTitle") };
}

/**
 * Organisation › Engagements (REQ-ENG-03): the organisation's engagements from GET /api/orgs/{org_id}/engagements,
 * those waiting on the organisation first ("Needs us"). Each row opens the tracker.
 */
export default async function OrganisationEngagementsPage({ searchParams }: PageProps<"/org/engagements">) {
  const me = await requireMe();
  const home = homeFor(me.side);
  if (home !== "/org") redirect(home);
  const t = await getTranslations("tracker");
  const org = pickOrg(me.memberships, (await searchParams).org);
  const read = org ? await orgEngagements(org.org_id) : null;

  return (
    <SignedInShell homeHref={home} wide>
      <div className="max-w-3xl">
        {read && !read.ok ? (
          <Refused refusal={read.refusal} backHref={home} />
        ) : (
          <>
            <h1 className="text-xl text-ink lg:text-2xl">{t("title")}</h1>
            <p className="mt-2 max-w-[62ch] text-ink-soft">{org ? t("orgLead") : t("noOrg")}</p>
            <div className="mt-8">
              {read?.ok && read.value.length > 0 ? (
                <EngagementList items={read.value} mine="org" basePath={ORG_ENGAGEMENTS_PATH} />
              ) : (
                <div data-empty-state="" className="flex flex-col items-start gap-3 border-t border-line pt-6">
                  <p className="max-w-[52ch] text-ink">{t("emptyOrg")}</p>
                  <Link href={home} className={standaloneLinkClass}>
                    {t("emptyOrgAction")}
                  </Link>
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </SignedInShell>
  );
}
