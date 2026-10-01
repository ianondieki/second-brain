import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { EmptyState } from "@/components/ui/EmptyState";
import { getProblem } from "@/components/problem/data";
import { ProblemCard } from "@/components/problem/ProblemCard";
import { PortalNavFor } from "@/components/PortalNavFor";
import { SignedInShell } from "@/components/SignedInShell";
import { BackLink } from "@/components/ui/BackLink";
import { ButtonLink } from "@/components/ui/ButtonLink";
import { PageHeader } from "@/components/ui/PageHeader";
import { requireMe } from "@/lib/api/server";
import { homeOf } from "@/lib/auth/routing";

import { DISCOVER_PATH, startProposalHref } from "../../dev/discover/discover";

export async function generateMetadata({ params }: PageProps<"/problems/[id]">): Promise<Metadata> {
  const t = await getTranslations("problem");
  const problem = await getProblem((await params).id).catch(() => null);
  return { title: problem?.title ?? t("pageTitle") };
}

/**
 * One published problem card with its citations (REQ-RES-02; GET /api/problems/{problem_id}), for every signed-in
 * side: developers reach it from Discover (P12-F), staff from the research review once a card is published. A
 * candidate, a rejected card and an unknown id read the same: not available (AC-RES-2).
 */
export default async function ProblemPage({ params }: PageProps<"/problems/[id]">) {
  const me = await requireMe();
  const home = homeOf(me);
  const t = await getTranslations("problem");
  const td = await getTranslations("discover");
  const problem = await getProblem((await params).id);
  // Developers come here from Discover and can start a proposal from the problem; other sides go back home.
  const developer = home === "/dev";
  const back = developer
    ? { href: DISCOVER_PATH, label: t("backToDiscover") }
    : { href: home, label: t("back") };
  return (
    <SignedInShell homeHref={home} nav={<PortalNavFor me={me} />} wide>
      <div className="max-w-3xl">
      {problem ? (
        <>
          <BackLink href={back.href}>{back.label}</BackLink>
          <ProblemCard
            problem={problem}
            action={
              developer ? (
                <ButtonLink href={startProposalHref(problem.id)} variant="primary">
                  {td("start")}
                </ButtonLink>
              ) : undefined
            }
          />
        </>
      ) : (
        <>
          <PageHeader title={t("pageTitle")} />
          <EmptyState sentence={t("notFound")} action={back.label} href={back.href} className="mt-8" />
        </>
      )}
      </div>
    </SignedInShell>
  );
}
