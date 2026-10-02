import { useTranslations } from "next-intl";

import { buttonClass } from "@/components/ui/Button";
import { ChevronDownIcon } from "@/components/ui/icons";
import { SelectField } from "@/components/ui/SelectField";
import { TabNav } from "@/components/ui/TabNav";

import {
  DISCOVER_PATH,
  discoverHref,
  isNarrowed,
  VIEWS,
  type CountyRef,
  type DiscoverQuery,
  type NicheNode,
} from "./discover";
import { StandaloneLink } from "@/components/ui/StandaloneLink";

/**
 * Discover's four lists as link tabs (TabNav: one at a time; the address holds the choice, so each list is
 * server-rendered and shareable).
 */
export function ViewSwitch({ query }: { query: DiscoverQuery }) {
  const t = useTranslations("discover");
  return (
    <TabNav
      label={t("viewsLabel")}
      current={query.view}
      items={VIEWS.map((view) => ({ key: view, label: t(`views.${view}`), href: discoverHref({ ...query, view }) }))}
    />
  );
}

export interface DiscoverFiltersProps {
  query: DiscoverQuery;
  niches: readonly NicheNode[];
  counties: readonly CountyRef[];
  /** "Clear filters" under the form; off when the empty state below already offers it as its one action. */
  showClear?: boolean;
}

/**
 * Niche and county as a plain GET form (works before JavaScript loads; the list stays on the chosen view). The
 * selects sit in a disclosure that starts open when one is set. "Show" is secondary: Discover's work is on the cards.
 */
export function DiscoverFilters({ query, niches, counties, showClear = true }: DiscoverFiltersProps) {
  const t = useTranslations("discover");
  const active = [query.niche, query.county].filter(Boolean).length;
  return (
    <form method="get" action={DISCOVER_PATH} role="search" aria-label={t("filters")}>
      {query.view !== "problems" ? <input type="hidden" name="view" value={query.view} /> : null}
      <details open={active > 0} className="group">
        <summary
          className={
            "inline-flex min-h-11 cursor-pointer list-none items-center gap-1.5 font-semibold text-accent " +
            "[&::-webkit-details-marker]:hidden"
          }
        >
          {active > 0 ? t("filtersChosen", { count: active }) : t("filters")}
          <ChevronDownIcon className="size-5 transition-transform duration-150 group-open:rotate-180 motion-reduce:transition-none" />
        </summary>
        <div className="mt-2 grid grid-cols-1 gap-4 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] sm:items-end">
          <SelectField id="discover-niche" name="niche" label={t("nicheLabel")} defaultValue={query.niche ?? ""}>
            <option value="">{t("nicheAll")}</option>
            {niches.map((parent) =>
              parent.children.length > 0 ? (
                <optgroup key={parent.id} label={parent.name}>
                  <option value={parent.slug}>{t("nicheAllIn", { niche: parent.name })}</option>
                  {parent.children.map((child) => (
                    <option key={child.id} value={child.slug}>
                      {child.name}
                    </option>
                  ))}
                </optgroup>
              ) : (
                <option key={parent.id} value={parent.slug}>
                  {parent.name}
                </option>
              ),
            )}
          </SelectField>
          <SelectField id="discover-county" name="county" label={t("countyLabel")} defaultValue={query.county ?? ""}>
            <option value="">{t("countyAll")}</option>
            {counties.map((county) => (
              <option key={county.code} value={county.code}>
                {county.name}
              </option>
            ))}
          </SelectField>
          <button type="submit" className={buttonClass("secondary", "sm:mb-0")}>
            {t("submit")}
          </button>
        </div>
        {showClear && isNarrowed(query) ? (
          <p className="mt-2">
            <StandaloneLink href={discoverHref({ view: query.view })}>
              {t("clear")}
            </StandaloneLink>
          </p>
        ) : null}
      </details>
    </form>
  );
}
