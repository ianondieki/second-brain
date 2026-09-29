import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { OrgNav } from "@/components/OrgNav";
import { SignedInShell } from "@/components/SignedInShell";
import { engagement } from "@/components/tracker/data";
import { asDocumentKind, asTab, EngagementScreen } from "@/components/tracker/EngagementScreen";
import { Refused } from "@/components/tracker/Refused";

import { orgContext } from "../../data";
import { ENGAGEMENTS_PATH, orgQuery } from "../../membership";

export async function generateMetadata({ params }: PageProps<"/org/engagements/[id]">): Promise<Metadata> {
  const t = await getTranslations("tracker");
  const found = await engagement((await params).id).catch(() => null);
  return { title: found?.ok ? found.value.proposal_title : t("pageTitle") };
}

/**
 * Organisation › Engagements › one tracker (REQ-ENG-03; docs/spec/06 6.9): the same tracker the developer sees. The
 * API decides access by the engagement's own organisation; the links keep that organisation (?org= for members of
 * several).
 */
export default async function OrganisationEngagementPage({ params, searchParams }: PageProps<"/org/engagements/[id]">) {
  const query = await searchParams;
  const { me, query: requested } = await orgContext(query.org);
  const found = await engagement((await params).id);
  // Links act for the engagement's own organisation, whatever ?org= said (the API decides access by it anyway).
  const orgParam = found.ok ? orgQuery(me.memberships, found.value.org_id) : requested;
  return (
    <SignedInShell homeHref={`/org${orgParam}`} nav={<OrgNav current="engagements" query={orgParam} />} wide>
      {found.ok ? (
        <EngagementScreen
          detail={found.value}
          me={me}
          tab={asTab(query.tab)}
          doc={asDocumentKind(query.doc)}
          basePath={ENGAGEMENTS_PATH}
          query={orgParam}
        />
      ) : (
        <Refused refusal={found.refusal} backHref={`${ENGAGEMENTS_PATH}${orgParam}`} />
      )}
    </SignedInShell>
  );
}
