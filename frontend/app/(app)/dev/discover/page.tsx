import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { directoryOptions } from "@/app/(app)/dev/companies/directory";
import { DevNav } from "@/components/DevNav";
import { SignedInShell } from "@/components/SignedInShell";
import { PageHero } from "@/components/ui/PageHero";
import { requireMe } from "@/lib/api/server";
import { homeFor } from "@/lib/auth/routing";

import { briefs, opportunityGap, savedSearches, trending } from "./data";
import { NICHES_PATH, parseDiscover } from "./discover";
import { DiscoverFilters, ViewSwitch } from "./DiscoverControls";
import { DiscoverList } from "./DiscoverList";
import { SavedSearchesPanel } from "./SavedSearchesPanel";
import { StandaloneLink } from "@/components/ui/StandaloneLink";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("discover");
  return { title: t("pageTitle") };
}

/**
 * Developer › Discover (REQ-TREND-02; docs/spec/06 6.6, docs/spec/07 item 1): Trending problems with their sources and
 * Why chips, Trending projects beside the problems they solve, the Opportunity gap and the organisations' Problem
 * Briefs (REQ-DIR-05), one list at a time, filtered
 * by niche, county and words, with the developer's saved searches under the filters (REQ-PERS-03, P21). Rendered on
 * the server from GET /api/discover/*; the saved searches strip is the one client island. Developers only; others go
 * to their own home.
 */
export default async function DiscoverPage({ searchParams }: PageProps<"/dev/discover">) {
  const me = await requireMe();
  const home = homeFor(me.side);
  if (home !== "/dev") redirect(home);
  const [t, te] = await Promise.all([getTranslations("discover"), getTranslations("eyebrow")]);
  const query = parseDiscover(await searchParams);
  const [lists, { niches, filterOptions }, saved] = await Promise.all([
    query.view === "gap"
      ? opportunityGap(query).then((gap) => ({ kind: "gap" as const, gap }))
      : query.view === "briefs"
        ? briefs(query).then((list) => ({ kind: "briefs" as const, briefs: list }))
        : trending(query).then((board) => ({ kind: "board" as const, board })),
    directoryOptions(),
    savedSearches(),
  ]);
  const empty =
    lists.kind === "gap"
      ? lists.gap.items.length === 0
      : lists.kind === "briefs"
        ? lists.briefs.items.length === 0
        : (query.view === "projects" ? lists.board.projects : lists.board.problems).length === 0;

  return (
    <SignedInShell homeHref={home} nav={<DevNav current="discover" />} wide>
      <div className="max-w-4xl">
        {/* No primary action: Discover's work is on the rows. "Your niches" is a secondary link in the action slot. */}
        <PageHero
          eyebrow={te("discover")}
          title={t("title")}
          lead={t("lead")}
          action={
            <StandaloneLink href={NICHES_PATH}>
              {t("yourNiches")}
            </StandaloneLink>
          }
        />
      </div>
      {/* The lists and their filters as one control surface: the tab strip on top, the filters under it. */}
      <div className="max-w-4xl rounded-panel border border-line bg-field">
        <ViewSwitch query={query} className="px-2 sm:px-3" />
        <div className="px-4 py-1 sm:px-5">
          <DiscoverFilters query={query} niches={niches} counties={filterOptions.counties} showClear={!empty} />
        </div>
        {saved ? (
          <SavedSearchesPanel list={saved} query={query} niches={niches} counties={filterOptions.counties} />
        ) : null}
      </div>
      <div className="mt-10 max-w-4xl lg:mt-12">
        <DiscoverList query={query} counties={filterOptions.counties} {...lists} />
      </div>
    </SignedInShell>
  );
}
