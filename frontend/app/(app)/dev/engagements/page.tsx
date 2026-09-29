import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { DevNav } from "@/components/DevNav";
import { SignedInShell } from "@/components/SignedInShell";
import { myEngagements } from "@/components/tracker/data";
import { EngagementList } from "@/components/tracker/EngagementList";
import { standaloneLinkClass } from "@/components/ui/Button";
import { requireMe } from "@/lib/api/server";
import { homeFor } from "@/lib/auth/routing";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("tracker");
  return { title: t("pageTitle") };
}

/**
 * Developer › Engagements (REQ-ENG-03): every organisation the developer pitched to, from GET /api/me/engagements,
 * those waiting on them first. Each row opens the tracker. No primary action: the list is for reading.
 */
export default async function DeveloperEngagementsPage() {
  const me = await requireMe();
  const home = homeFor(me.side);
  if (home !== "/dev") redirect(home);
  const t = await getTranslations("tracker");
  const items = await myEngagements();

  return (
    <SignedInShell homeHref={home} nav={<DevNav current="engagements" />} wide>
      <div className="max-w-3xl">
        <h1 className="text-xl text-ink lg:text-2xl">{t("title")}</h1>
        <p className="mt-2 max-w-[62ch] text-ink-soft">{t("devLead")}</p>
        <div className="mt-8">
          {items.length > 0 ? (
            <EngagementList items={items} mine="developer" basePath="/dev/engagements" />
          ) : (
            <div data-empty-state="" className="flex flex-col items-start gap-3 border-t border-line pt-6">
              <p className="max-w-[52ch] text-ink">{t("emptyDev")}</p>
              <Link href="/dev/ideas" className={standaloneLinkClass}>
                {t("emptyDevAction")}
              </Link>
            </div>
          )}
        </div>
      </div>
    </SignedInShell>
  );
}
