import { useTranslations } from "next-intl";

import { buttonClass, primaryMark } from "@/components/ui/Button";
import { ChevronDownIcon } from "@/components/ui/icons";
import { SelectField } from "@/components/ui/SelectField";
import { TextField } from "@/components/ui/TextField";

import {
  activeFilterCount,
  BASE_PATH,
  isNarrowed,
  ORG_KINDS,
  type DirectoryFilters as Filters,
  type FilterOptions,
  type NicheNode,
} from "./filters";
import { StandaloneLink } from "@/components/ui/StandaloneLink";

export interface DirectoryFiltersProps {
  filters: Filters;
  niches: NicheNode[];
  options: FilterOptions;
  /** "Clear filters" under the form; off when the empty state below already offers it as its one action. */
  showClear?: boolean;
}

/**
 * Search and filters as a plain GET form: the URL holds the state, so results are server-rendered, shareable and
 * work before JavaScript loads (docs/spec/07 item 5). The name search stays in view; niche, org type and county sit in
 * a disclosure that starts open when one is set; "Show companies" (the screen's one primary action) comes after them.
 */
export function DirectoryFilters({ filters, niches, options, showClear = true }: DirectoryFiltersProps) {
  const t = useTranslations("companies");
  const kinds = useTranslations("orgKind");
  const active = activeFilterCount(filters);

  return (
    <form method="get" action={BASE_PATH} role="search" className="flex flex-col gap-4">
      <TextField
        id="directory-q"
        name="q"
        type="search"
        label={t("searchLabel")}
        defaultValue={filters.q}
        maxLength={100}
        autoComplete="off"
        enterKeyHint="search"
      />

      <details open={active > 0} className="group">
        <summary
          className={
            "inline-flex min-h-11 cursor-pointer list-none items-center gap-1.5 font-semibold text-accent " +
            "[&::-webkit-details-marker]:hidden"
          }
        >
          {active > 0 ? t("filtersChosen", { count: active }) : t("filters")}
          <ChevronDownIcon className="size-5 transition-transform duration-150 group-open:rotate-180" />
        </summary>
        <div className="mt-2 grid grid-cols-1 gap-4 sm:grid-cols-3">
          <SelectField id="directory-niche" name="niche" label={t("nicheLabel")} defaultValue={filters.niche ?? ""}>
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
          <SelectField id="directory-kind" name="kind" label={t("kindLabel")} defaultValue={filters.kind ?? ""}>
            <option value="">{t("kindAll")}</option>
            {ORG_KINDS.filter((kind) => options.org_types.some((option) => option.value === kind)).map((kind) => (
              <option key={kind} value={kind}>
                {kinds(kind)}
              </option>
            ))}
          </SelectField>
          <SelectField id="directory-county" name="county" label={t("countyLabel")} defaultValue={filters.county ?? ""}>
            <option value="">{t("countyAll")}</option>
            {options.counties.map((county) => (
              <option key={county.code} value={county.code}>
                {county.name}
              </option>
            ))}
          </SelectField>
        </div>
      </details>

      {/* After every field it submits, in reading and tab order (ux item 12). A plain GET form on a server page: the
          Button component's click handler cannot cross to the browser. */}
      <div>
        <button type="submit" className={buttonClass("primary")} {...primaryMark("primary")}>
          {t("submit")}
        </button>
      </div>

      {showClear && isNarrowed(filters) ? (
        <p>
          <StandaloneLink href={BASE_PATH}>
            {t("clear")}
          </StandaloneLink>
        </p>
      ) : null}
    </form>
  );
}
