import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { DevNav } from "@/components/DevNav";
import { SignedInShell } from "@/components/SignedInShell";
import { myEngagements } from "@/components/tracker/data";
import { EngagementCard } from "@/components/engagements/EngagementCard";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHero } from "@/components/ui/PageHero";
import { Section } from "@/components/ui/Section";
import { requireMe } from "@/lib/api/server";
import { homeFor } from "@/lib/auth/routing";

import { myIdeas } from "../ideas/data";

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
  const te = await getTranslations("eyebrow");
  const [engagements, ideas] = await Promise.all([myEngagements(), myIdeas().catch(() => [])]);
  const groups = byProposal(engagements);
  // Each idea's niche, for its cards' photograph band (D-67).
  const nicheOf = new Map(ideas.map((idea) => [idea.id, idea.niche ?? null]));

  return (
    <SignedInShell homeHref={home} nav={<DevNav current="engagements" />} wide>
      <div className="max-w-5xl">
        <PageHero eyebrow={te("engagements")} title={t("title")} lead={t("devLead")} />
        {groups.length > 0 ? (
          <div className="flex flex-col gap-12 lg:gap-14">
            {groups.map((group) => (
              // Each idea is a section of its organisations' cards; the card that waits on the developer is raised.
              <Section
                key={group.proposalId}
                title={group.title}
                headingId={`proposal-${group.proposalId}`}
                description={td("organisations", { count: group.items.length })}
                link={{ href: `/dev/ideas/${encodeURIComponent(group.proposalId)}`, label: td("openIdea") }}
                data-proposal={group.proposalId}
              >
                {/* As many 20 rem columns as fit, sharing the width: one card is never left narrow beside empty room. */}
                <ul aria-label={td("rowsLabel", { title: group.title })} className="grid gap-4 sm:grid-cols-[repeat(auto-fit,minmax(20rem,1fr))]">
                  {group.items.map((item) => (
                    <li key={item.id} className="cv-auto flex min-w-0 [--cv-size:18rem] [&>article]:flex-1">
                      <EngagementCard
                        item={item}
                        mine="developer"
                        titleBy="organisation"
                        href={`/dev/engagements/${encodeURIComponent(item.id)}`}
                        niche={nicheOf.get(item.proposal_id) ?? null}
                      />
                    </li>
                  ))}
                </ul>
              </Section>
            ))}
          </div>
        ) : (
          <EmptyState sentence={t("emptyDev")} action={t("emptyDevAction")} href="/dev/ideas" />
        )}
      </div>
    </SignedInShell>
  );
}
