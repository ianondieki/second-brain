import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { DevNav } from "@/components/DevNav";
import { SignedInShell } from "@/components/SignedInShell";
import { engagement } from "@/components/tracker/data";
import { asDocumentKind, asTab, EngagementScreen } from "@/components/tracker/EngagementScreen";
import { Refused } from "@/components/tracker/Refused";
import { requireMe } from "@/lib/api/server";
import { homeFor } from "@/lib/auth/routing";

const BASE_PATH = "/dev/engagements";

export async function generateMetadata({ params }: PageProps<"/dev/engagements/[id]">): Promise<Metadata> {
  const t = await getTranslations("tracker");
  const found = await engagement((await params).id).catch(() => null);
  return { title: found?.ok ? found.value.proposal_title : t("pageTitle") };
}

/** Developer › Engagements › one tracker (REQ-ENG-03; docs/spec/06 6.9). */
export default async function DeveloperEngagementPage({ params, searchParams }: PageProps<"/dev/engagements/[id]">) {
  const me = await requireMe();
  const home = homeFor(me.side);
  if (home !== "/dev") redirect(home);
  const { id } = await params;
  const query = await searchParams;
  // The Messages tab is its own route; old links and the N18 notices (?tab=messages) land there.
  if (query.tab === "messages") redirect(`${BASE_PATH}/${encodeURIComponent(id)}/messages`);
  const found = await engagement(id);
  return (
    <SignedInShell homeHref={home} nav={<DevNav current="engagements" />} wide>
      {found.ok ? (
        <EngagementScreen
          detail={found.value}
          me={me}
          tab={asTab(query.tab)}
          doc={asDocumentKind(query.doc)}
          basePath={BASE_PATH}
        />
      ) : (
        <Refused refusal={found.refusal} backHref={BASE_PATH} />
      )}
    </SignedInShell>
  );
}
