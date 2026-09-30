import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { directoryOptions } from "@/app/(app)/dev/companies/directory";
import { EmptyState } from "@/app/(app)/org/EmptyState";
import { ClientStrings } from "@/components/ClientStrings";
import { DevNav } from "@/components/DevNav";
import { SignedInShell } from "@/components/SignedInShell";
import { standaloneLinkClass } from "@/components/ui/Button";
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
      <p className="-mt-2 mb-4">
        <Link href={DISCOVER_PATH} className={standaloneLinkClass}>
          {t("back")}
        </Link>
      </p>
      <h1 className="text-xl text-ink lg:text-2xl">{t("title")}</h1>
      {liked ? (
        <>
          <p className="mt-2 text-ink-soft">{t("lead", { count: liked.min, max: liked.max })}</p>
          <p className="mt-1 text-sm text-ink-soft">{t("keep", { count: liked.min })}</p>
          <ClientStrings strings={strings}>
            <div className="mt-8">
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
        <div className="mt-6">
          <EmptyState sentence={t("problem.noProfile")} action={t("back")} href={DISCOVER_PATH} />
        </div>
      )}
    </SignedInShell>
  );
}
