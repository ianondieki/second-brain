import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { SignedInShell } from "@/components/SignedInShell";
import { engagement } from "@/components/tracker/data";
import { asDocumentKind, asTab, EngagementScreen } from "@/components/tracker/EngagementScreen";
import { Refused } from "@/components/tracker/Refused";
import { requireMe } from "@/lib/api/server";
import { homeFor } from "@/lib/auth/routing";

import { ORG_ENGAGEMENTS_PATH } from "../org";

export async function generateMetadata({ params }: PageProps<"/org/engagements/[id]">): Promise<Metadata> {
  const t = await getTranslations("tracker");
  const found = await engagement((await params).id).catch(() => null);
  return { title: found?.ok ? found.value.proposal_title : t("pageTitle") };
}

/** Organisation › Engagements › one tracker (REQ-ENG-03; docs/spec/06 6.9): the same tracker the developer sees. */
export default async function OrganisationEngagementPage({ params, searchParams }: PageProps<"/org/engagements/[id]">) {
  const me = await requireMe();
  const home = homeFor(me.side);
  if (home !== "/org") redirect(home);
  const found = await engagement((await params).id);
  const query = await searchParams;
  return (
    <SignedInShell homeHref={home} wide>
      {found.ok ? (
        <EngagementScreen
          detail={found.value}
          me={me}
          tab={asTab(query.tab)}
          doc={asDocumentKind(query.doc)}
          basePath={ORG_ENGAGEMENTS_PATH}
        />
      ) : (
        <Refused refusal={found.refusal} backHref={ORG_ENGAGEMENTS_PATH} />
      )}
    </SignedInShell>
  );
}
