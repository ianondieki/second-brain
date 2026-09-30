import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { EmptyState } from "@/components/ui/EmptyState";
import { getProblem } from "@/components/problem/data";
import { ProblemCard } from "@/components/problem/ProblemCard";
import { SignedInShell } from "@/components/SignedInShell";
import { BackLink } from "@/components/ui/BackLink";
import { requireMe } from "@/lib/api/server";
import { homeOf } from "@/lib/auth/routing";

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
  const problem = await getProblem((await params).id);
  return (
    <SignedInShell homeHref={home}>
      {problem ? (
        <>
          <BackLink href={home}>{t("back")}</BackLink>
          <ProblemCard problem={problem} />
        </>
      ) : (
        <>
          <h1 className="text-xl text-ink lg:text-2xl">{t("pageTitle")}</h1>
          <div className="mt-6">
            <EmptyState sentence={t("notFound")} action={t("back")} href={home} />
          </div>
        </>
      )}
    </SignedInShell>
  );
}
