import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { DevNav } from "@/components/DevNav";
import { SignedInShell } from "@/components/SignedInShell";
import { Alert } from "@/components/ui/Alert";
import { ButtonLink } from "@/components/ui/ButtonLink";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { RowList } from "@/components/ui/RowList";
import { requireMe } from "@/lib/api/server";
import { homeFor } from "@/lib/auth/routing";

import { myIdeas } from "./data";
import { NEW_PATH } from "./ideas";
import { IdeaCard } from "./IdeaCard";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("ideas");
  return { title: t("pageTitle") };
}

/**
 * Developer › My ideas (REQ-PROP-01, F2): your drafts and published ideas from GET /api/me/proposals, newest change
 * first, each with its status. "New idea" is the screen's one primary action; with no ideas it is the empty state's
 * one action instead (docs/spec/07 items 2 and 4).
 */
export default async function MyIdeasPage({ searchParams }: PageProps<"/dev/ideas">) {
  const me = await requireMe();
  const home = homeFor(me.side);
  if (home !== "/dev") redirect(home);
  const t = await getTranslations("ideas");
  const items = await myIdeas();
  const removed = (await searchParams).removed;

  return (
    <SignedInShell homeHref={home} nav={<DevNav current="ideas" />} wide>
      <div className="max-w-3xl">
        <PageHeader
          title={t("title")}
          lead={t("lead")}
          action={
            items.length > 0 ? (
              <ButtonLink href={NEW_PATH} variant="primary">
                {t("newIdea")}
              </ButtonLink>
            ) : undefined
          }
        />
      </div>

      {removed === "hidden" || removed === "deleted" ? (
        <Alert tone="ok" className="mt-6 max-w-3xl">
          {t(removed === "hidden" ? "removedHidden" : "removedDeleted")}
        </Alert>
      ) : null}

      <div className="mt-8 max-w-3xl lg:mt-10">
        {items.length > 0 ? (
          <RowList aria-label={t("listLabel")}>
            {items.map((item) => (
              <IdeaCard key={item.id} item={item} version />
            ))}
          </RowList>
        ) : (
          <EmptyState sentence={t("empty")} action={t("newIdea")} href={NEW_PATH} primary />
        )}
      </div>
    </SignedInShell>
  );
}
