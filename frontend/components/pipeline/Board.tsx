import { getTranslations } from "next-intl/server";

import { AssigneeFilter } from "@/components/team/AssigneeFilter";
import { ClockTicker } from "@/components/ui/ClockTicker";
import { EmptyState } from "@/components/ui/EmptyState";

import { BoardCard } from "./BoardCard";
import type { Pipeline } from "./data";
import { Funnel } from "./Funnel";

export interface BoardProps {
  pipeline: Pipeline;
  /** A card's tracker ("/org/engagements/<id>?org=…"). */
  cardHref: (id: string) => string;
  /** The "Assigned to me" filter, when the cards carry the organisation's triage facts. */
  filter?: { on: boolean; allHref: string; mineHref: string };
  /** The empty board's one action (set up a scout). */
  emptyHref: string;
}

/**
 * The Board tab of the organisation's Engagements (P27 track B; REQ-ENG-14), server-rendered: the funnel strip of the
 * last 90 days, then the five stage groups as columns, each headed by its name, count and median days in stage, its
 * cards compact (BoardCard). The columns are one row that scrolls sideways inside itself, a column about 85 % of a
 * phone's width (18 rem at most) and snapping into place, the page itself never wider than the screen; from 1280 px
 * the five stand side by side (at 1024 px the portal's rail leaves the main column too narrow for five). "Assigned to
 * me" narrows the cards (a link pair; the address keeps the choice). The cards' clocks tick from the page's one script.
 */
export async function Board({ pipeline, cardHref, filter, emptyHref }: BoardProps) {
  const [t, tt] = await Promise.all([getTranslations("pipeline"), getTranslations("tracker")]);
  const total = pipeline.columns.reduce((sum, column) => sum + column.items.length, 0);
  // The same "Assigned to me" links as the list and the Inbox (`?assignee=me`).
  const filterBar = filter ? (
    <AssigneeFilter mine={filter.on} allHref={filter.allHref} mineHref={filter.mineHref} />
  ) : null;

  if (total === 0 && filter?.on) {
    return (
      <div className="flex flex-col gap-6" data-board="">
        {filterBar}
        <EmptyState
          sentence={t("emptyMine")}
          action={t("emptyMineAction")}
          href={filter.allHref}
          data-board="mine-empty"
        />
      </div>
    );
  }
  if (total === 0 && Object.values(pipeline.funnel.entered).every((n) => n === 0)) {
    return <EmptyState sentence={t("empty")} action={t("emptyAction")} href={emptyHref} data-board="empty" />;
  }
  return (
    <div className="flex flex-col gap-10" data-board="">
      <Funnel funnel={pipeline.funnel} />
      {/* Not a landmark itself: the row below is the region the heading names. */}
      <div className="flex flex-col gap-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 id="columns-title" className="sr-only">
            {t("columnsLabel")}
          </h2>
          {filterBar}
        </div>
        <div
          role="region"
          aria-labelledby="columns-title"
          // A keyboard user can scroll the row (it takes focus); the page never widens (the row scrolls in itself).
          tabIndex={0}
          className="-mx-4 snap-x snap-mandatory overflow-x-auto overscroll-x-contain px-4 pb-2 [scroll-padding-inline:1rem] sm:-mx-6 sm:px-6 lg:mx-0 lg:px-0 xl:overflow-visible xl:pb-0"
          data-board-row=""
        >
          <ol className="flex gap-3 xl:grid xl:grid-cols-5">
            {pipeline.columns.map((column) => (
              <li
                key={column.group}
                data-column={column.group}
                className="flex w-[85vw] max-w-72 shrink-0 snap-start flex-col gap-3 xl:w-auto xl:max-w-none xl:min-w-0"
              >
                <section aria-labelledby={`column-${column.group}`} className="flex min-w-0 flex-col gap-3">
                  <header className="flex flex-col gap-0.5 border-b border-line pb-2">
                    <h3 id={`column-${column.group}`} className="text-lg text-ink">
                      {tt(`group.${column.group}`)}
                    </h3>
                    <p className="text-sm font-semibold text-ink" data-count={column.count}>
                      {t("count", { count: column.count })}
                    </p>
                    {column.median_days_in_stage !== null ? (
                      <p className="text-sm text-ink-soft" data-median={column.median_days_in_stage}>
                        {t("median", { days: Math.round(column.median_days_in_stage) })}
                      </p>
                    ) : null}
                  </header>
                  {column.items.length > 0 ? (
                    <ul className="flex flex-col gap-3">
                      {column.items.map((item) => (
                        <li key={item.id}>
                          <BoardCard
                            item={item}
                            href={cardHref(item.id)}
                            now={pipeline.now}
                            stalledAfter={pipeline.stalled_after_bd}
                          />
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-sm text-ink-soft">{t("columnEmpty")}</p>
                  )}
                </section>
              </li>
            ))}
          </ol>
        </div>
      </div>
      <ClockTicker />
    </div>
  );
}
