import { useTranslations } from "next-intl";

import { EmptyState } from "@/components/ui/EmptyState";
import { Section } from "@/components/ui/Section";
import { StandaloneLink } from "@/components/ui/StandaloneLink";

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
import { sectionBands } from "./bands";
import { OrgTile } from "./OrgTile";

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
        <Group
          key={`${group.niche?.id ?? "none"}-${index}`}
          group={group}
          filters={filters}
          // The count is the section's whole only when the list is: one page, no page before it or after it.
          counted={!filters.cursor && !page.next_cursor}
        />
      ))}
      {filters.cursor || page.next_cursor ? (
        <nav aria-label={t("pages")} className="flex flex-wrap items-center justify-between gap-x-8 gap-y-2">
          {filters.cursor ? <StandaloneLink href={firstPage}>{t("firstPage")}</StandaloneLink> : <span />}
          {page.next_cursor ? (
            <StandaloneLink href={filtersHref({ ...filters, cursor: page.next_cursor })}>
              {t("nextPage")}
            </StandaloneLink>
          ) : null}
        </nav>
      ) : null}
    </div>
  );
}

/**
 * One niche's organisations (AC-DIR-6): a Section titled with the niche's two-level name (the parent niche quieter,
 * in the same line: no label above it) and, when the whole list is on this one page (`counted`), how many
 * organisations it holds (a paged list would count only this page's), then the organisations as cards, two across
 * from 640 px, each card four rows the grid shares (subgrid). The section picks the cards' bands (bands.ts): each
 * card its own county's photographs in turn, the crop cycling.
 */
function Group({ group, filters, counted }: { group: DirectoryGroup; filters: DirectoryFilters; counted: boolean }) {
  const t = useTranslations("companies");
  const bands = sectionBands(group.orgs, group.niche?.slug);
  return (
    <Section
      title={group.niche ? <NicheTitle label={group.niche.label} /> : t("noNiche")}
      description={counted ? t("groupCount", { count: group.orgs.length }) : undefined}
      data-niche={group.niche?.slug ?? "none"}
    >
      <ul className="grid grid-cols-1 gap-x-5 gap-y-5 sm:grid-cols-2">
        {group.orgs.map((org, index) => (
          <OrgTile key={org.id} org={org} filters={filters} groupNiche={group.niche?.slug} band={bands[index]} />
        ))}
      </ul>
    </Section>
  );
}

/** "ICT › Networks & Telecoms": the parent niche in the quieter ink, the niche itself in ink; one heading's words. */
function NicheTitle({ label }: { label: string }) {
  const { parent, name } = splitNicheLabel(label);
  if (!parent) return <>{name}</>;
  return (
    <>
      <span className="text-ink-soft">{parent} ›</span> {name}
    </>
  );
}
