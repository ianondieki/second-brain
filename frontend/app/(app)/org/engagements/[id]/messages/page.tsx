import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { OrgNav } from "@/components/OrgNav";
import { SignedInShell } from "@/components/SignedInShell";
import { engagement } from "@/components/tracker/data";
import { MessagesScreen } from "@/components/tracker/MessagesScreen";
import { Refused } from "@/components/tracker/Refused";

import { orgContext } from "../../../data";
import { ENGAGEMENTS_PATH, orgQuery } from "../../../membership";

export async function generateMetadata({ params }: PageProps<"/org/engagements/[id]/messages">): Promise<Metadata> {
  const t = await getTranslations("tracker");
  const found = await engagement((await params).id).catch(() => null);
  return { title: found?.ok ? t("messages.pageTitle", { title: found.value.proposal_title }) : t("pageTitle") };
}

/**
 * Organisation › Engagements › one engagement's Messages tab (REQ-ENG-11): the same thread the developer sees. Before
 * INTEREST_CONFIRMED the API refuses the organisation the thread (AC-TRACK-9) and the tab says when it opens.
 */
export default async function OrganisationMessagesPage({ params, searchParams }: PageProps<"/org/engagements/[id]/messages">) {
  const query = await searchParams;
  const { me, query: requested } = await orgContext(query.org);
  const found = await engagement((await params).id);
  const orgParam = found.ok ? orgQuery(me.memberships, found.value.org_id) : requested;
  return (
    <SignedInShell homeHref={`/org${orgParam}`} nav={<OrgNav current="engagements" query={orgParam} />} wide>
      {found.ok ? (
        <MessagesScreen detail={found.value} basePath={ENGAGEMENTS_PATH} query={orgParam} />
      ) : (
        <Refused refusal={found.refusal} backHref={`${ENGAGEMENTS_PATH}${orgParam}`} />
      )}
    </SignedInShell>
  );
}
