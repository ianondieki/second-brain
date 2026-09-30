import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { DevNav } from "@/components/DevNav";
import { SignedInShell } from "@/components/SignedInShell";
import { myEngagements } from "@/components/tracker/data";
import { EngagementRow } from "@/components/tracker/EngagementRow";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { RowList } from "@/components/ui/RowList";
import { Section } from "@/components/ui/Section";
import { requireMe } from "@/lib/api/server";
import { homeFor } from "@/lib/auth/routing";

import { byProposal } from "./byProposal";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("tracker");
  return { title: t("pageTitle") };
}

/**
 * Developer › Engagements (REQ-ENG-03; docs/spec/07 item 1): every organisation the developer pitched to, from
 * GET /api/me/engagements, grouped by proposal with one row per organisation; proposals and rows waiting on the
 * developer first. Each row opens the tracker; each proposal links to its idea page. No primary action: the list is
 * for reading.
 */
export default async function DeveloperEngagementsPage() {
  const me = await requireMe();
  const home = homeFor(me.side);
  if (home !== "/dev") redirect(home);
  const t = await getTranslations("tracker");
  const td = await getTranslations("devEngagements");
  const groups = byProposal(await myEngagements());

  return (
    <SignedInShell homeHref={home} nav={<DevNav current="engagements" />} wide>
      <div className="max-w-3xl">
        <PageHeader title={t("title")} lead={t("devLead")} />
        {groups.length > 0 ? (
          <div className="mt-10 flex flex-col gap-12">
            {groups.map((group) => (
              <Section
                key={group.proposalId}
                title={group.title}
                headingId={`proposal-${group.proposalId}`}
                description={td("organisations", { count: group.items.length })}
                link={{ href: `/dev/ideas/${encodeURIComponent(group.proposalId)}`, label: td("openIdea") }}
                data-proposal={group.proposalId}
              >
                <RowList aria-label={td("rowsLabel", { title: group.title })}>
                  {group.items.map((item) => (
                    <EngagementRow
                      key={item.id}
                      item={item}
                      mine="developer"
                      href={`/dev/engagements/${encodeURIComponent(item.id)}`}
                    />
                  ))}
                </RowList>
              </Section>
            ))}
          </div>
        ) : (
          <EmptyState sentence={t("emptyDev")} action={t("emptyDevAction")} href="/dev/ideas" className="mt-8" />
        )}
      </div>
    </SignedInShell>
  );
}
