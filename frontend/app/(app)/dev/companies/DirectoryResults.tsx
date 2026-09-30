import Link from "next/link";
import { useTranslations } from "next-intl";

import { standaloneLinkClass } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";

import {
  BASE_PATH,
  countOrgs,
  filtersHref,
  isNarrowed,
  splitNicheLabel,
  type DirectoryFilters,
  type DirectoryGroup,
  type DirectoryPage,
} from "./filters";
import { OrgRow } from "./OrgRow";

export type ResultsProps =
  | { kind: "page"; page: DirectoryPage; filters: DirectoryFilters }
  | { kind: "staleCursor"; filters: DirectoryFilters };

/**
 * The directory list: organisations under niche headings (the API's order; organisations without a niche last),
 * then paging. Empty and stale states are one sentence and one action (docs/spec/07 item 4).
 */
export function DirectoryResults(props: ResultsProps) {
  const t = useTranslations("companies");
  const { filters } = props;
  const firstPage = filtersHref({ ...filters, cursor: undefined });

  if (props.kind === "staleCursor") {
    return <EmptyState sentence={t("staleCursor")} action={t("firstPage")} href={firstPage} />;
  }
  const { page } = props;
  if (countOrgs(page) === 0) {
    if (filters.cursor) return <EmptyState sentence={t("staleCursor")} action={t("firstPage")} href={firstPage} />;
    return isNarrowed(filters) ? (
      <EmptyState sentence={t("emptyFiltered")} action={t("clear")} href={BASE_PATH} />
    ) : (
      <EmptyState sentence={t("emptyAll")} action={t("goHome")} href="/dev" />
    );
  }

  return (
    <div>
      {page.groups.map((group, index) => (
        <Group key={`${group.niche?.id ?? "none"}-${index}`} group={group} filters={filters} />
      ))}
      {filters.cursor || page.next_cursor ? (
        <nav aria-label={t("pages")} className="mt-10 flex flex-wrap items-center justify-between gap-x-8 gap-y-2">
          {filters.cursor ? (
            <Link href={firstPage} className={standaloneLinkClass}>
              {t("firstPage")}
            </Link>
          ) : (
            <span />
          )}
          {page.next_cursor ? (
            <Link href={filtersHref({ ...filters, cursor: page.next_cursor })} className={standaloneLinkClass}>
              {t("nextPage")}
            </Link>
          ) : null}
        </nav>
      ) : null}
    </div>
  );
}

function Group({ group, filters }: { group: DirectoryGroup; filters: DirectoryFilters }) {
  const t = useTranslations("companies");
  const label = group.niche ? splitNicheLabel(group.niche.label) : null;
  return (
    <section className="mt-10 first:mt-0">
      <h2 className="flex flex-col text-lg text-ink">
        {label?.parent ? (
          <span className="text-sm font-medium tracking-normal text-ink-soft">{label.parent}</span>
        ) : null}
        <span>{label ? label.name : t("noNiche")}</span>
      </h2>
      <div className="mt-2 grid grid-cols-1 gap-x-10 md:grid-cols-2">
        {group.orgs.map((org) => (
          <OrgRow key={org.id} org={org} filters={filters} />
        ))}
      </div>
    </section>
  );
}
