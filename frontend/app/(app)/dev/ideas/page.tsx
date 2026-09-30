import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { DevNav } from "@/components/DevNav";
import { SignedInShell } from "@/components/SignedInShell";
import { Alert } from "@/components/ui/Alert";
import { ButtonLink } from "@/components/ui/ButtonLink";
import { EmptyState } from "@/components/ui/EmptyState";
import { requireMe } from "@/lib/api/server";
import { homeFor } from "@/lib/auth/routing";

import { myIdeas } from "./data";
import { NEW_PATH } from "./ideas";
import { IdeaRow } from "./IdeaRow";

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
      <div className="flex max-w-3xl flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-xl text-ink lg:text-2xl">{t("title")}</h1>
          <p className="mt-2 max-w-[62ch] text-ink-soft">{t("lead")}</p>
        </div>
        {items.length > 0 ? (
          <ButtonLink href={NEW_PATH} variant="primary" className="shrink-0">
            {t("newIdea")}
          </ButtonLink>
        ) : null}
      </div>

      {removed === "hidden" || removed === "deleted" ? (
        <Alert tone="ok" className="mt-6 max-w-3xl">
          {t(removed === "hidden" ? "removedHidden" : "removedDeleted")}
        </Alert>
      ) : null}

      <div className="mt-8 max-w-3xl">
        {items.length > 0 ? (
          <ul aria-label={t("listLabel")} className="border-b border-line">
            {items.map((item) => (
              <li key={item.id}>
                <IdeaRow item={item} />
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState sentence={t("empty")} action={t("newIdea")} href={NEW_PATH} primary />
        )}
      </div>
    </SignedInShell>
  );
}
