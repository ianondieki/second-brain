import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { directoryOptions } from "@/app/(app)/dev/companies/directory";
import { DevNav } from "@/components/DevNav";
import { SignedInShell } from "@/components/SignedInShell";
import { standaloneLinkClass } from "@/components/ui/Button";
import { requireMe } from "@/lib/api/server";
import { homeFor } from "@/lib/auth/routing";

import { opportunityGap, trending } from "./data";
import { NICHES_PATH, parseDiscover } from "./discover";
import { DiscoverFilters, ViewSwitch } from "./DiscoverControls";
import { DiscoverList } from "./DiscoverList";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("discover");
  return { title: t("pageTitle") };
}

/**
 * Developer › Discover (REQ-TREND-02; docs/spec/06 6.6, docs/spec/07 item 1): Trending problems with their sources and
 * Why chips, Trending projects beside the problems they solve, and the Opportunity gap, one list at a time, filtered
 * by niche and county. Rendered on the server from GET /api/discover/*; no script beyond the framework's. Developers
 * only; others go to their own home.
 */
export default async function DiscoverPage({ searchParams }: PageProps<"/dev/discover">) {
  const me = await requireMe();
  const home = homeFor(me.side);
  if (home !== "/dev") redirect(home);
  const t = await getTranslations("discover");
  const query = parseDiscover(await searchParams);
  const [lists, { niches, filterOptions }] = await Promise.all([
    query.view === "gap"
      ? opportunityGap(query).then((gap) => ({ kind: "gap" as const, gap }))
      : trending(query).then((board) => ({ kind: "board" as const, board })),
    directoryOptions(),
  ]);
  const empty =
    lists.kind === "gap"
      ? lists.gap.items.length === 0
      : (query.view === "projects" ? lists.board.projects : lists.board.problems).length === 0;

  return (
    <SignedInShell homeHref={home} nav={<DevNav current="discover" />} wide>
      <div className="flex max-w-3xl flex-col gap-2 sm:flex-row sm:items-start sm:justify-between sm:gap-6">
        <div className="min-w-0">
          <h1 className="text-xl text-ink lg:text-2xl">{t("title")}</h1>
          <p className="mt-2 max-w-[62ch] text-ink-soft">{t("lead")}</p>
        </div>
        <Link href={NICHES_PATH} className={`${standaloneLinkClass} shrink-0 sm:mt-1`}>
          {t("yourNiches")}
        </Link>
      </div>
      <div className="mt-6 flex max-w-3xl flex-col gap-3">
        <ViewSwitch query={query} />
        <DiscoverFilters query={query} niches={niches} counties={filterOptions.counties} showClear={!empty} />
      </div>
      <div className="mt-8 max-w-3xl">
        <DiscoverList query={query} counties={filterOptions.counties} {...lists} />
      </div>
    </SignedInShell>
  );
}
