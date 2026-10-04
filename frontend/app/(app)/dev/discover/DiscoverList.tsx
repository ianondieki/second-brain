import { useTranslations } from "next-intl";
import type { ReactNode } from "react";

import { EmptyState } from "@/components/ui/EmptyState";
import { RowList } from "@/components/ui/RowList";
import { Section } from "@/components/ui/Section";

import {
  discoverHref,
  isColdStart,
  isNarrowed,
  MAX_ITEMS,
  projectsById,
  type CountyRef,
  type DiscoverBriefsOut,
  type DiscoverQuery,
  type OpportunityGapOut,
  type TrendingOut,
  type TrendingProject,
} from "./discover";
import { BriefRow } from "./BriefRow";
import { ProblemRow } from "./ProblemRow";
import { ProjectRow } from "./ProjectRow";

export type DiscoverListProps = { query: DiscoverQuery; counties: readonly CountyRef[] } & (
  | { kind: "board"; board: TrendingOut }
  | { kind: "gap"; gap: OpportunityGapOut }
  | { kind: "briefs"; briefs: DiscoverBriefsOut }
);

/**
 * The chosen list with its heading and one line on what it holds, its items as compact cards two across from 640 px
 * (D-52, as Home's recommendations). Cold start (nothing in the list trends yet) titles the problems or the projects
 * "New this week". An empty list is one sentence and one action (docs/spec/07 item 4): clear the filters when they
 * narrowed it, else the next useful step.
 */
export function DiscoverList(props: DiscoverListProps) {
  const t = useTranslations("discover");
  const { query, counties } = props;
  const narrowed = isNarrowed(query);
  const clear = { sentence: t("filteredEmpty"), action: t("clear"), href: discoverHref({ view: query.view }) };

  if (props.kind === "briefs") {
    const items = props.briefs.items.slice(0, MAX_ITEMS);
    return (
      <List id="discover-briefs" title={t("briefsTitle")} lead={t("briefsLead")}>
        {items.length === 0 ? (
          <EmptyState
            {...(narrowed ? clear : { sentence: t("briefsEmpty"), action: t("toProblems"), href: discoverHref({}) })}
          />
        ) : (
          <RowList ordered cards>
            {items.map((item) => (
              <BriefRow key={item.problem.id} item={item} counties={counties} />
            ))}
          </RowList>
        )}
      </List>
    );
  }

  if (props.kind === "gap") {
    const items = props.gap.items.slice(0, MAX_ITEMS);
    return (
      <List id="discover-gap" title={t("gapTitle")} lead={t("gapLead")}>
        {items.length === 0 ? (
          <EmptyState
            {...(narrowed ? clear : { sentence: t("gapEmpty"), action: t("toProblems"), href: discoverHref({}) })}
          />
        ) : (
          <RowList ordered cards>
            {items.map((item) => (
              <ProblemRow key={item.problem.id} item={item} counties={counties} query={query} />
            ))}
          </RowList>
        )}
      </List>
    );
  }

  const { board } = props;
  if (query.view === "projects") {
    const items = board.projects.slice(0, MAX_ITEMS);
    const coldProjects = isColdStart(items);
    return (
      <List
        id="discover-projects"
        title={coldProjects ? t("coldTitle") : t("projectsTitle")}
        lead={coldProjects ? t("coldProjectsLead") : t("projectsLead")}
      >
        {items.length === 0 ? (
          <EmptyState
            {...(narrowed ? clear : { sentence: t("projectsEmpty"), action: t("toProblems"), href: discoverHref({}) })}
          />
        ) : (
          <RowList ordered cards>
            {items.map((item) => (
              <ProjectRow key={item.proposal.id} item={item} />
            ))}
          </RowList>
        )}
      </List>
    );
  }

  const items = board.problems.slice(0, MAX_ITEMS);
  const cold = isColdStart(items);
  const projects = projectsById(board.projects);
  return (
    <List
      id="discover-problems"
      title={cold ? t("coldTitle") : t("problemsTitle")}
      lead={cold ? t("coldLead") : t("problemsLead")}
    >
      {items.length === 0 ? (
        <EmptyState
          {...(narrowed
            ? clear
            : { sentence: t("problemsEmpty"), action: t("problemsEmptyAction"), href: "/dev/ideas/new" })}
        />
      ) : (
        <RowList ordered cards>
          {items.map((item) => (
            <ProblemRow
              key={item.problem.id}
              item={item}
              counties={counties}
              query={query}
              projects={item.project_ids
                .map((id) => projects.get(id))
                .filter((project): project is TrendingProject => project !== undefined)}
            />
          ))}
        </RowList>
      )}
    </List>
  );
}

/** One list: its heading, one line on what it holds, then the rows (Section). */
function List({ id, title, lead, children }: { id: string; title: string; lead: string; children: ReactNode }) {
  return (
    <Section title={title} headingId={id} description={lead} data-list={id}>
      {children}
    </Section>
  );
}
