import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { DevNav } from "@/components/DevNav";
import { SignedInShell } from "@/components/SignedInShell";
import { engagement } from "@/components/tracker/data";
import { MessagesScreen } from "@/components/tracker/MessagesScreen";
import { Refused } from "@/components/tracker/Refused";
import { requireMe } from "@/lib/api/server";
import { homeFor } from "@/lib/auth/routing";

const BASE_PATH = "/dev/engagements";

export async function generateMetadata({ params }: PageProps<"/dev/engagements/[id]/messages">): Promise<Metadata> {
  const t = await getTranslations("tracker");
  const found = await engagement((await params).id).catch(() => null);
  return { title: found?.ok ? t("messages.pageTitle", { title: found.value.proposal_title }) : t("pageTitle") };
}

/** Developer › Engagements › one engagement's Messages tab (REQ-ENG-11; docs/spec/07 item 1). */
export default async function DeveloperMessagesPage({ params }: PageProps<"/dev/engagements/[id]/messages">) {
  const me = await requireMe();
  const home = homeFor(me.side);
  if (home !== "/dev") redirect(home);
  const found = await engagement((await params).id);
  return (
    <SignedInShell homeHref={home} nav={<DevNav current="engagements" />} wide>
      {found.ok ? (
        <MessagesScreen detail={found.value} basePath={BASE_PATH} />
      ) : (
        <Refused refusal={found.refusal} backHref={BASE_PATH} />
      )}
    </SignedInShell>
  );
}
