import Link from "next/link";
import { useTranslations } from "next-intl";

import { buttonClass, standaloneLinkClass } from "@/components/ui/Button";
import { cn } from "@/components/ui/cn";
import { ChevronDownIcon } from "@/components/ui/icons";
import { SelectField } from "@/components/ui/SelectField";

import {
  DISCOVER_PATH,
  discoverHref,
  isNarrowed,
  VIEWS,
  type CountyRef,
  type DiscoverQuery,
  type NicheNode,
} from "./discover";

/**
 * Discover's three lists as links (one at a time; the address holds the choice, so each list is server-rendered and
 * shareable). The current one carries aria-current and is marked by weight and a bar, not colour alone.
 */
export function ViewSwitch({ query }: { query: DiscoverQuery }) {
  const t = useTranslations("discover");
  return (
    <nav aria-label={t("viewsLabel")} className="border-b border-line">
      <ul className="-mb-px flex gap-5 overflow-x-auto sm:gap-8">
        {VIEWS.map((view) => {
          const active = view === query.view;
          return (
            <li key={view} className="shrink-0">
              <Link
                href={discoverHref({ ...query, view })}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "inline-flex min-h-11 items-center border-b-2 pb-0.5 whitespace-nowrap no-underline",
                  active
                    ? "border-jacaranda font-semibold text-ink"
                    : "border-transparent font-medium text-ink-soft hover:border-line hover:text-ink",
                )}
              >
                {t(`views.${view}`)}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
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
            "inline-flex min-h-11 cursor-pointer list-none items-center gap-1.5 font-semibold text-jacaranda " +
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
            <Link href={discoverHref({ view: query.view })} className={standaloneLinkClass}>
              {t("clear")}
            </Link>
          </p>
        ) : null}
      </details>
    </form>
  );
}
