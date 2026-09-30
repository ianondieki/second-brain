import { useTranslations } from "next-intl";
import type { ReactNode } from "react";

import { EmptyState } from "@/components/ui/EmptyState";

import {
  discoverHref,
  isColdStart,
  isNarrowed,
  MAX_ITEMS,
  projectsById,
  type CountyRef,
  type DiscoverQuery,
  type OpportunityGapOut,
  type TrendingOut,
  type TrendingProject,
} from "./discover";
import { ProblemRow } from "./ProblemRow";
import { ProjectRow } from "./ProjectRow";

export type DiscoverListProps = { query: DiscoverQuery; counties: readonly CountyRef[] } & (
  | { kind: "board"; board: TrendingOut }
  | { kind: "gap"; gap: OpportunityGapOut }
);

/**
 * The chosen list with its heading and one line on what it holds. Cold start (nothing in the list trends yet) titles
 * the problems or the projects "New this week". An empty list is one sentence and one action (docs/spec/07 item 4): clear the filters when they
 * narrowed it, else the next useful step.
 */
export function DiscoverList(props: DiscoverListProps) {
  const t = useTranslations("discover");
  const { query, counties } = props;
  const narrowed = isNarrowed(query);
  const clear = { sentence: t("filteredEmpty"), action: t("clear"), href: discoverHref({ view: query.view }) };

  if (props.kind === "gap") {
    const items = props.gap.items.slice(0, MAX_ITEMS);
    return (
      <Section id="discover-gap" title={t("gapTitle")} lead={t("gapLead")}>
        {items.length === 0 ? (
          <EmptyState
            {...(narrowed ? clear : { sentence: t("gapEmpty"), action: t("toProblems"), href: discoverHref({}) })}
          />
        ) : (
          <ol className="border-b border-line">
            {items.map((item) => (
              <li key={item.problem.id}>
                <ProblemRow item={item} counties={counties} query={query} />
              </li>
            ))}
          </ol>
        )}
      </Section>
    );
  }

  const { board } = props;
  if (query.view === "projects") {
    const items = board.projects.slice(0, MAX_ITEMS);
    const coldProjects = isColdStart(items);
    return (
      <Section
        id="discover-projects"
        title={coldProjects ? t("coldTitle") : t("projectsTitle")}
        lead={coldProjects ? t("coldProjectsLead") : t("projectsLead")}
      >
        {items.length === 0 ? (
          <EmptyState
            {...(narrowed ? clear : { sentence: t("projectsEmpty"), action: t("toProblems"), href: discoverHref({}) })}
          />
        ) : (
          <ol className="border-b border-line">
            {items.map((item) => (
              <li key={item.proposal.id}>
                <ProjectRow item={item} />
              </li>
            ))}
          </ol>
        )}
      </Section>
    );
  }

  const items = board.problems.slice(0, MAX_ITEMS);
  const cold = isColdStart(items);
  const projects = projectsById(board.projects);
  return (
    <Section
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
        <ol className="border-b border-line">
          {items.map((item) => (
            <li key={item.problem.id}>
              <ProblemRow
                item={item}
                counties={counties}
                query={query}
                projects={item.project_ids
                  .map((id) => projects.get(id))
                  .filter((project): project is TrendingProject => project !== undefined)}
              />
            </li>
          ))}
        </ol>
      )}
    </Section>
  );
}

function Section({ id, title, lead, children }: { id: string; title: string; lead: string; children: ReactNode }) {
  return (
    <section aria-labelledby={id} data-list={id}>
      <h2 id={id} className="text-lg text-ink">
        {title}
      </h2>
      <p className="mt-1 mb-3 max-w-[62ch] text-sm text-ink-soft">{lead}</p>
      {children}
    </section>
  );
}
