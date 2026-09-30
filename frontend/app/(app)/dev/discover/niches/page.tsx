import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { directoryOptions } from "@/app/(app)/dev/companies/directory";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { ClientStrings } from "@/components/ClientStrings";
import { DevNav } from "@/components/DevNav";
import { SignedInShell } from "@/components/SignedInShell";
import { requireMe } from "@/lib/api/server";
import { homeFor } from "@/lib/auth/routing";
import { clientStrings } from "@/lib/i18n/client-strings";

import { likedNiches, profilingConsent } from "../data";
import { DISCOVER_PATH } from "../discover";
import { NichePicker, type PickerNiche } from "./NichePicker";
import { ProfilingToggle } from "./ProfilingToggle";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("likedNiches");
  return { title: t("pageTitle") };
}

/**
 * The niches a developer likes (REQ-PERS-03; GET|PUT /api/me/niches), reached from Discover and from Home's
 * "Recommended for you", and the profiling consent that decides whether the ranking also uses their activity
 * (REQ-PERS-01, D-47). Developers only.
 */
export default async function LikedNichesPage() {
  const me = await requireMe();
  const home = homeFor(me.side);
  if (home !== "/dev") redirect(home);
  const t = await getTranslations("likedNiches");
  const [liked, { niches }, consent, strings] = await Promise.all([
    likedNiches(),
    directoryOptions(),
    profilingConsent(),
    clientStrings(["likedNiches"]),
  ]);
  // Only names and ids reach the browser.
  const options: PickerNiche[] = niches.map((parent) => ({
    id: parent.id,
    name: parent.name,
    children: parent.children.map((child) => ({ id: child.id, name: child.name })),
  }));

  return (
    <SignedInShell homeHref={home} nav={<DevNav current="discover" />}>
      <PageHeader
        back={{ href: DISCOVER_PATH, label: t("back") }}
        title={t("title")}
        lead={liked ? t("lead", { count: liked.min, max: liked.max }) : undefined}
      >
        {liked ? <p className="mt-1 text-sm text-ink-soft">{t("keep", { count: liked.min })}</p> : null}
      </PageHeader>
      {liked ? (
        <>
          <ClientStrings strings={strings}>
            <div className="mt-10">
              <NichePicker niches={options} initial={liked.liked.map((niche) => niche.id)} min={liked.min} max={liked.max} />
            </div>
            {consent ? (
              <div className="mt-12">
                <ProfilingToggle consent={consent} />
              </div>
            ) : null}
          </ClientStrings>
        </>
      ) : (
        <EmptyState sentence={t("problem.noProfile")} action={t("back")} href={DISCOVER_PATH} className="mt-8" />
      )}
    </SignedInShell>
  );
}
