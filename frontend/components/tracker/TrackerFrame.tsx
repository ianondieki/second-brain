import { getLocale, getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import { Avatar } from "@/components/ui/Avatar";
import { cn } from "@/components/ui/cn";
import { Lattice } from "@/components/ui/Lattice";
import { PageHeader } from "@/components/ui/PageHeader";
import { TabNav } from "@/components/ui/TabNav";
import { formatDay } from "@/lib/format";

import { counterpartLine, isFinished, stageLeft, stepperSteps, turnOf, withQuery, type Detail, type History } from "./model";
import { Stepper } from "./Stepper";
import { WhoseTurn } from "./WhoseTurn";

// The parts of one engagement's page that every tab shares (docs/spec/06 6.9, docs/spec/07 item 1): the title, the
// turn card, the five-stage spine and the tab bar. Server components only, so a tab's own client code is all a route
// adds: the Tracker, Documents and History tabs (EngagementScreen, /…/engagements/[id]) carry the turn card's buttons,
// the Messages tab (MessagesScreen, /…/engagements/[id]/messages) carries the thread instead (the 150 KB budget).

/** The tabs, in the order the bar shows them. Messages is its own route; the others are views of the tracker's. */
export const TAB_LINKS = ["tracker", "documents", "messages", "history"] as const;
export type TabLink = (typeof TAB_LINKS)[number];

/** One engagement's page in its portal ("/dev/engagements/<id>"). */
export function engagementHref(basePath: string, id: string): string {
  return `${basePath}/${encodeURIComponent(id)}`;
}

/** Where each tab lives: the tracker's own page with ?tab=, or the Messages route; the org's ?org= kept. */
export function tabHref(href: string, query: string, tab: TabLink): string {
  if (tab === "messages") return withQuery(`${href}/messages`, query);
  return withQuery(href, query, tab === "tracker" ? {} : { tab });
}

export async function TrackerHeader({ detail, basePath, query }: { detail: Detail; basePath: string; query: string }) {
  const t = await getTranslations("tracker");
  const line = counterpartLine(detail);
  return (
    <PageHeader
      className="max-w-3xl"
      back={{ href: withQuery(basePath, query), label: t("back") }}
      title={detail.proposal_title}
      lead={<span data-counterpart={line.key}>{t(line.key, line.values)}</span>}
    />
  );
}

/**
 * The turn card: the page's headline object. Whose turn, the next step and the countdown, then `children` (the
 * caller's buttons, or on the Messages tab the way to them) in a band that hides while it is empty. Raised and edged
 * with the lattice when it is the viewer's turn; a flat card otherwise.
 */
export function TurnCard({ detail, children }: { detail: Detail; children?: ReactNode }) {
  const turn = turnOf(detail, detail.my_party);
  const yours = turn.kind === "you" || turn.kind === "both";
  return (
    <div
      data-turn-card={yours ? "yours" : "theirs"}
      className={cn("mt-8 max-w-3xl overflow-hidden rounded-panel border border-line bg-field", yours && "shadow-card")}
    >
      {yours ? <Lattice /> : null}
      <WhoseTurn detail={detail} />
      {children ? <div className="border-t border-line p-5 has-[>div:empty]:hidden sm:px-7 sm:py-6">{children}</div> : null}
    </div>
  );
}

/** Whether the spine needs the history: an ended engagement has no stage group, and its history says which it left. */
export function needsHistory(detail: Detail): boolean {
  return (isFinished(detail.state) && detail.state !== "CLOSED") || (detail.stage_group === null && !detail.paused_from);
}

/** The visual spine: the five stages on the canvas, a vertical timeline on phones and a line across from 1024 px. */
export async function TrackerSpine({ detail, history }: { detail: Detail; history: History | null }) {
  const t = await getTranslations("tracker");
  const locale = await getLocale();
  const steps = stepperSteps({ ...detail, left: stageLeft(detail.state, history?.events) });
  // The party who acts now: the developer, the organisation, or both (the timeline shows them at the step).
  const awaited = new Set(detail.whose_turn);
  const actors = isFinished(detail.state) ? null : (
    <span className="flex shrink-0 items-center gap-1">
      {awaited.has("developer") ? <Avatar name={detail.developer_name} kind="person" size="sm" active /> : null}
      {awaited.has("org") ? <Avatar name={detail.org_name} kind="org" size="sm" active /> : null}
    </span>
  );
  return (
    <div className="mt-10 max-w-3xl">
      <Stepper
        steps={steps}
        actor={actors}
        detail={
          <>
            {/* On hold the chip already says it: no "Now: On hold" under "On hold". */}
            {detail.state === "ON_HOLD" ? null : (
              <span className="block font-semibold">{t("stageNow", { stage: detail.stage_label })}</span>
            )}
            {!isFinished(detail.state) ? (
              <span className="block text-ink-soft">{t("since", { date: formatDay(locale, detail.stage_entered_at) })}</span>
            ) : null}
          </>
        }
      />
    </div>
  );
}

/** The tab bar; Messages shows the unread count (the figure for the eye, words for screen readers) unless it is open. */
export async function TrackerTabs({
  detail,
  current,
  basePath,
  query,
}: {
  detail: Detail;
  current: TabLink;
  basePath: string;
  query: string;
}) {
  const t = await getTranslations("tracker");
  const href = engagementHref(basePath, detail.id);
  const unread = detail.unread_messages ?? 0;
  return (
    <TabNav
      label={t("tabs.label")}
      current={current}
      className="mt-10 max-w-3xl"
      items={TAB_LINKS.map((name) => ({
        key: name,
        label:
          name === "messages" && unread > 0 && current !== "messages" ? (
            <>
              {t("tabs.messages")}
              <span
                aria-hidden="true"
                data-unread={unread}
                className="ml-1.5 inline-grid h-5 min-w-5 place-items-center rounded-full bg-accent px-1.5 text-xs font-bold text-on-accent tabular-nums"
              >
                {unread}
              </span>{" "}
              <span className="sr-only">{t("unread", { count: unread })}</span>
            </>
          ) : (
            t(`tabs.${name}`)
          ),
        href: tabHref(href, query, name),
      }))}
    />
  );
}
