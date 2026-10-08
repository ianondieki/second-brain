import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { OrgNav } from "@/components/OrgNav";
import { SignedInShell } from "@/components/SignedInShell";
import { orgEngagements } from "@/components/tracker/data";
import { EngagementList } from "@/components/tracker/EngagementList";

import { orgContext } from "../data";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHero } from "@/components/ui/PageHero";
import { ENGAGEMENTS_PATH, inboxHref, type Membership } from "../membership";
import { OrgPicker } from "../OrgPicker";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("tracker");
  return { title: t("pageTitle") };
}

/**
 * Organisation › Engagements (REQ-ENG-03): the organisation's engagements from GET /api/orgs/{org_id}/engagements,
 * those waiting on the organisation first ("Needs us"). Each row opens the tracker. Members of several organisations
 * pick one (?org=); an organisation the person is not a member of is refused, never silently swapped.
 */
export default async function OrganisationEngagementsPage({ searchParams }: PageProps<"/org/engagements">) {
  const { memberships, org, missing, query } = await orgContext((await searchParams).org);
  const [t, ti, tp] = await Promise.all([getTranslations("tracker"), getTranslations("inbox"), getTranslations("portal")]);

  return (
    <SignedInShell homeHref={`/org${query}`} nav={<OrgNav current="engagements" query={query} />} wide>
      <div className="max-w-5xl">
        <PageHero eyebrow={tp("eyebrow.engagements")} title={t("title")} lead={org ? t("orgLead") : undefined} />
        {org ? (
          <Body memberships={memberships} org={org} query={query} />
        ) : (
          <div>
            {missing === "notMember" ? (
              <EmptyState sentence={t("notMember")} action={t("openOwn")} href={ENGAGEMENTS_PATH} />
            ) : (
              <EmptyState sentence={ti("noOrg")} action={ti("emptyAction")} href="/org" />
            )}
          </div>
        )}
      </div>
    </SignedInShell>
  );
}

async function Body({ memberships, org, query }: { memberships: Membership[]; org: Membership; query: string }) {
  const t = await getTranslations("tracker");
  const read = await orgEngagements(org.org_id);
  let body;
  if (!read.ok) {
    body =
      read.refusal === "mfaSetup" ? (
        <EmptyState sentence={t("refused.mfaSetup")} action={t("turnOnMfa")} href="/settings/security" primary />
      ) : (
        <EmptyState sentence={t("refused.notFound")} action={t("emptyOrgAction")} href={inboxHref(memberships, org.org_id)} />
      );
  } else if (read.value.length === 0) {
    body = <EmptyState sentence={t("emptyOrg")} action={t("emptyOrgAction")} href={inboxHref(memberships, org.org_id)} />;
  } else {
    body = <EngagementList items={read.value} mine="org" basePath={ENGAGEMENTS_PATH} query={query} />;
  }
  return (
    <>
      {memberships.length > 1 ? (
        <div className="mb-6">
          <OrgPicker memberships={memberships} current={org.org_id} action={ENGAGEMENTS_PATH} />
        </div>
      ) : null}
      <div className="max-w-3xl">{body}</div>
    </>
  );
}
