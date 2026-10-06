import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { getLocale, getTranslations } from "next-intl/server";

import { ClientStrings } from "@/components/ClientStrings";
import { DevNav } from "@/components/DevNav";
import { SignedInShell } from "@/components/SignedInShell";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { StandaloneLink } from "@/components/ui/StandaloneLink";
import { requireMe } from "@/lib/api/server";
import { homeFor } from "@/lib/auth/routing";
import { clientStrings } from "@/lib/i18n/client-strings";

import { nicheNamesBySlug, peerRelations, peersPage } from "../teams/data";
import { PROFILE_SETTINGS_PATH, TEAMS_PATH } from "../teams/teams";
import { PeerList } from "./PeerList";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("teams");
  return { title: t("peers.pageTitle") };
}

/**
 * Developer › Peers (REQ-DEV-03; D-58): the developers in the caller's county or niches who are visible to peers, by
 * handle, twenty a page, each with "Team up" (an invitation tied to a published problem or Brief) and "Block" in its
 * overflow menu. Reached from Home's Peers section (no nav item of its own: the developer nav stays at five,
 * principle 6). Not visible to peers: one sentence and the way to Settings. Developers only; organisations go to
 * their own home, as from every developer route.
 */
export default async function PeersPage() {
  const me = await requireMe();
  const home = homeFor(me.side);
  if (home !== "/dev") redirect(home);
  const [t, locale, page, niches, relations] = await Promise.all([
    getTranslations("teams"),
    getLocale(),
    peersPage(),
    nicheNamesBySlug(),
    peerRelations(),
  ]);
  const visible = page !== "tooMany" && page.opted_in;

  return (
    <SignedInShell homeHref="/dev" nav={<DevNav current="home" />} wide>
      <div className="flex max-w-3xl flex-col gap-8">
        <PageHeader back={{ href: "/dev", label: t("peers.back") }} title={t("peers.title")} lead={t("peers.lead")}>
          {/* Not visible to peers: the page's one sentence and link are about turning it on, nothing else. */}
          {visible ? (
            <div className="mt-2">
              <StandaloneLink href={TEAMS_PATH}>{t("peers.teamsLink")}</StandaloneLink>
            </div>
          ) : null}
        </PageHeader>

        {page === "tooMany" ? (
          <EmptyState data-peers="too-many" sentence={t("peers.tooMany")} action={t("peers.tooManyAction")} href="/dev" />
        ) : !page.opted_in ? (
          <EmptyState data-peers="off" sentence={t("peers.off")} action={t("peers.turnOn")} href={PROFILE_SETTINGS_PATH} />
        ) : page.peers.length === 0 ? (
          <EmptyState data-peers="empty" sentence={t("peers.empty")} action={t("peers.emptyAction")} href={PROFILE_SETTINGS_PATH} />
        ) : (
          <ClientStrings strings={await clientStrings(["teamUp"])}>
            <PeerList initial={page} niches={niches} relations={relations} locale={locale} />
          </ClientStrings>
        )}
      </div>
    </SignedInShell>
  );
}
