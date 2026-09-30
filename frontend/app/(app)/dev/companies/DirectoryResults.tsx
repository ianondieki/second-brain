import Link from "next/link";
import { useTranslations } from "next-intl";

import { standaloneLinkClass } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { RowList } from "@/components/ui/RowList";
import { Section } from "@/components/ui/Section";

import {
  BASE_PATH,
  countOrgs,
  filtersHref,
  isNarrowed,
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
    <div className="flex flex-col gap-12">
      {page.groups.map((group, index) => (
        <Group key={`${group.niche?.id ?? "none"}-${index}`} group={group} filters={filters} />
      ))}
      {filters.cursor || page.next_cursor ? (
        <nav aria-label={t("pages")} className="flex flex-wrap items-center justify-between gap-x-8 gap-y-2">
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

/** One niche's organisations: a Section titled with the niche's two-level name (no label above it), rows of two. */
function Group({ group, filters }: { group: DirectoryGroup; filters: DirectoryFilters }) {
  const t = useTranslations("companies");
  return (
    <Section title={group.niche ? group.niche.label : t("noNiche")}>
      <RowList className="md:grid md:grid-cols-2 md:gap-x-10">
        {group.orgs.map((org) => (
          <OrgRow key={org.id} org={org} filters={filters} />
        ))}
      </RowList>
    </Section>
  );
}
