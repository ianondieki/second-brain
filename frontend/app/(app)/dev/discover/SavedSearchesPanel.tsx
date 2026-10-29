import { getTranslations } from "next-intl/server";

import { ClientStrings } from "@/components/ClientStrings";
import { clientStrings } from "@/lib/i18n/client-strings";

import { discoverHref, nicheOptions, type CountyRef, type DiscoverQuery, type NicheNode } from "./discover";
import { MAX_NAME, savesView, type SavedSearchList, type SavedSearchRow } from "./saved-searches";
import { SavedSearches, type CurrentSearch } from "./SavedSearches";

type Filters = Pick<DiscoverQuery, "view" | "niche" | "county" | "words">;

/**
 * The saved searches strip under Discover's filters (REQ-PERS-03), with every word formatted here: each search's
 * filters in words (the list, the niche and county by name, the words in quotes) and a name to start from for the
 * current view. The panel itself is the client island SavedSearches.
 */
export async function SavedSearchesPanel({
  list,
  query,
  niches,
  counties,
}: {
  list: SavedSearchList;
  query: DiscoverQuery;
  niches: readonly NicheNode[];
  counties: readonly CountyRef[];
}) {
  const t = await getTranslations("discover");
  const names = new Map(nicheOptions(niches).map((niche) => [niche.slug, niche.name]));
  const county = (code?: string | null) => (code ? (counties.find((c) => c.code === code)?.name ?? code) : undefined);
  const niche = (slug?: string | null) => (slug ? (names.get(slug) ?? slug) : undefined);

  const facts = ({ view, niche: slug, county: code, words }: Filters): string[] =>
    [
      t(`views.${view}`),
      niche(slug),
      county(code),
      words ? t("wordsQuoted", { words }) : undefined,
    ].filter((fact): fact is string => Boolean(fact));

  const rows: SavedSearchRow[] = list.items.map((saved) => {
    const filters = { view: saved.view, niche: saved.niche ?? undefined, county: saved.county ?? undefined, words: saved.words ?? undefined };
    return { id: saved.id, name: saved.name, alerts: saved.alerts, href: discoverHref(filters), facts: facts(filters) };
  });

  let current: CurrentSearch | null = null;
  const { view } = query;
  if (savesView(view)) {
    const n = niche(query.niche);
    const c = county(query.county);
    const viewName = t(`views.${view}`);
    const suggested = n && c
      ? t("saveName.nicheCounty", { niche: n, county: c })
      : n
        ? n
        : c
          ? t("saveName.viewCounty", { view: viewName, county: c })
          : query.words
            ? t("wordsQuoted", { words: query.words })
            : t("saveName.all", { view: viewName });
    current = {
      query: { ...query, view },
      suggestedName: suggested.slice(0, MAX_NAME),
      href: discoverHref(query),
      facts: facts(query),
    };
  }

  return (
    <ClientStrings strings={await clientStrings(["savedSearches"])}>
      {/* Keyed by the search on screen: applying a saved search (or any filter) starts the strip afresh, closed and
          with the list as the server read it. */}
      <SavedSearches
        key={discoverHref(query)}
        initial={rows}
        max={list.max}
        current={current}
        settingsHref="/settings/notifications"
      />
    </ClientStrings>
  );
}
