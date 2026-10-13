import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { OrgNav } from "@/components/OrgNav";
import { OfflineSlot } from "@/components/offline/OfflineSlot";
import { SignedInShell } from "@/components/SignedInShell";
import { orgEngagements } from "@/components/tracker/data";
import { CsvExport } from "@/components/engagements/CsvExport";
import { EngagementCard } from "@/components/engagements/EngagementCard";
import { AssigneeFilter, assignedToMe, assigneeLine, isAssignedTo } from "@/components/team/AssigneeFilter";
import { awaitsMe, type OrgSummary } from "@/components/tracker/model";
import { Section } from "@/components/ui/Section";
import { appNow } from "@/lib/api/server";

import { getTeaser, orgContext } from "../data";
import { CalendarView } from "@/components/deadlines/CalendarView";
import { EngagementTabs, pickView, viewHref } from "@/components/engagements/EngagementTabs";
import { Board } from "@/components/pipeline/Board";
import { assignedTo, hasTeamFacts, readPipeline } from "@/components/pipeline/data";
import { ClockTicker } from "@/components/ui/ClockTicker";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHero } from "@/components/ui/PageHero";
import { ENGAGEMENTS_PATH, inboxHref, orgQuery, type Membership } from "../membership";
import { OrgPicker } from "../OrgPicker";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("tracker");
  return { title: t("pageTitle") };
}

/**
 * Organisation › Engagements (REQ-ENG-03; D-67): the organisation's engagements from GET /api/orgs/{org_id}/engagements
 * as cards (five-dot stage line, whose turn), those waiting on the organisation first ("Needs us"). Each card opens the
 * tracker. Members of several organisations
 * pick one (?org=); an organisation the person is not a member of is refused, never silently swapped.
 */
export default async function OrganisationEngagementsPage({ searchParams }: PageProps<"/org/engagements">) {
  const params = await searchParams;
  const { me, memberships, org, missing, query } = await orgContext(params.org);
  const mine = assignedToMe(params.assignee);
  const view = pickView(params.view, true);
  // The organisation's id in the views' links only when the person has several (as `query`).
  const orgParam = org && memberships.length > 1 ? org.org_id : undefined;
  const [t, ti, tp] = await Promise.all([
    getTranslations("tracker"),
    getTranslations("inbox"),
    getTranslations("portal"),
  ]);

  return (
    <SignedInShell
      homeHref={`/org${query}`}
      nav={<OrgNav current="engagements" query={query} />}
      wide
      // The Board's five columns run on to the window's right edge from 1152 px; the List and Calendar keep the frame.
      bleed={view === "board"}
      offline={<OfflineSlot page={(await getTranslations("nav"))("engagements")} />}
    >
      <div className={view === "board" ? undefined : "max-w-5xl"}>
        <PageHero
          eyebrow={tp("eyebrow.engagements")}
          title={t("title")}
          lead={org ? t("orgLead") : undefined}
          tabs={org ? <EngagementTabs basePath={ENGAGEMENTS_PATH} current={view} board org={orgParam} /> : undefined}
        />
        {org && view !== "list" && memberships.length > 1 ? (
          <div className="mb-6">
            <OrgPicker memberships={memberships} current={org.org_id} action={ENGAGEMENTS_PATH} keep={{ view }} />
          </div>
        ) : null}
        {org && view === "calendar" ? (
          <CalendarView
            basePath={ENGAGEMENTS_PATH}
            orgId={org.org_id}
            orgQuery={orgParam}
            month={params.month}
            day={params.day}
            side="org"
            emptyHref={inboxHref(memberships, org.org_id)}
          />
        ) : org && view === "board" ? (
          <BoardView orgId={org.org_id} orgParam={orgParam} query={query} mine={mine} userId={me.user.id} />
        ) : org ? (
          <Body memberships={memberships} org={org} query={query} userId={me.user.id} mine={mine} />
        ) : (
          <div>
            {missing === "notMember" ? (
              <EmptyState sentence={t("notMember")} action={t("openOwn")} href={ENGAGEMENTS_PATH} />
            ) : (
              <EmptyState sentence={ti("noOrg")} action={ti("emptyAction")} href="/org" />
            )}
          </div>
        )}
      </div>
    </SignedInShell>
  );
}

/**
 * The Board view (P27 track B; REQ-ENG-14): the organisation's pipeline, narrowed to the person's own engagements with
 * "Assigned to me" (`?assignee=me`), a filter offered only when the cards carry the organisation's triage facts.
 */
async function BoardView({
  orgId,
  orgParam,
  query,
  mine,
  userId,
}: {
  orgId: string;
  orgParam?: string;
  query: string;
  mine: boolean;
  userId: string;
}) {
  const t = await getTranslations("tracker");
  const read = await readPipeline(orgId);
  if (!read.ok) {
    return read.refusal === "mfaSetup" ? (
      <EmptyState sentence={t("refused.mfaSetup")} action={t("turnOnMfa")} href="/settings/security" primary />
    ) : (
      <EmptyState sentence={t("refused.notFound")} action={t("back")} href={`${ENGAGEMENTS_PATH}${query}`} />
    );
  }
  const filterable = hasTeamFacts(read.value);
  const on = filterable && mine;
  return (
    <Board
      pipeline={on ? assignedTo(read.value, userId) : read.value}
      cardHref={(id) => `${ENGAGEMENTS_PATH}/${encodeURIComponent(id)}${query}`}
      filter={
        filterable
          ? {
              on,
              allHref: viewHref(ENGAGEMENTS_PATH, "board", { org: orgParam }),
              mineHref: viewHref(ENGAGEMENTS_PATH, "board", { org: orgParam, assignee: "me" }),
            }
          : undefined
      }
      emptyHref={`/org/inbox/scouts/new${query}`}
    />
  );
}

async function Body({
  memberships,
  org,
  query,
  userId,
  mine,
}: {
  memberships: Membership[];
  org: Membership;
  query: string;
  userId: string;
  /** "Assigned to me" (`?assignee=me`): only the engagements assigned to the caller. */
  mine: boolean;
}) {
  const t = await getTranslations("tracker");
  const te = await getTranslations("engagements");
  const read = await orgEngagements(org.org_id);
  const allHref = `${ENGAGEMENTS_PATH}${orgQuery(memberships, org.org_id)}`;
  // The "Assigned to me" filter and, at the row's end, "Export CSV" or the plan that has it (REQ-ENG-17).
  const filter =
    read.ok && read.value.length > 0 ? (
      <div className="mb-6 flex flex-wrap items-center justify-between gap-x-6 gap-y-3" data-list-tools="">
        <AssigneeFilter
          mine={mine}
          allHref={allHref}
          mineHref={`${ENGAGEMENTS_PATH}${orgQuery(memberships, org.org_id, { assignee: "me" })}`}
        />
        <CsvExport orgId={org.org_id} />
      </div>
    ) : null;
  const shown =
    read.ok && mine ? read.value.filter((item) => isAssignedTo(item.team, userId)) : read.ok ? read.value : [];
  let body;
  if (!read.ok) {
    body =
      read.refusal === "mfaSetup" ? (
        <EmptyState sentence={t("refused.mfaSetup")} action={t("turnOnMfa")} href="/settings/security" primary />
      ) : (
        <EmptyState
          sentence={t("refused.notFound")}
          action={t("emptyOrgAction")}
          href={inboxHref(memberships, org.org_id)}
        />
      );
  } else if (read.value.length === 0) {
    body = (
      <EmptyState sentence={t("emptyOrg")} action={t("emptyOrgAction")} href={inboxHref(memberships, org.org_id)} />
    );
  } else if (shown.length === 0) {
    body = <EmptyState sentence={te("noneMine")} action={te("showAll")} href={allHref} />;
  } else {
    body = (
      <>
        <EngagementGrid items={shown} query={query} userId={userId} />
        {/* The cards' clocks tick from one script for the page, after them (no island per card). */}
        <ClockTicker />
      </>
    );
  }
  return (
    <>
      {memberships.length > 1 ? (
        <div className="mb-6">
          <OrgPicker memberships={memberships} current={org.org_id} action={ENGAGEMENTS_PATH} />
        </div>
      ) : null}
      {filter}
      {body}
    </>
  );
}

/**
 * The organisation's engagements as cards (components/engagements/EngagementCard, as the developer's list): those
 * waiting on the organisation first, under "Needs us", then the rest under their own heading; with one group only, the
 * cards stand under the page's title, their titles a level up (no lone heading).
 */
async function EngagementGrid({ items, query, userId }: { items: OrgSummary[]; query: string; userId: string }) {
  const t = await getTranslations("tracker");
  // Each proposal's niche, for its cards' photograph band (D-67), from its public teaser (Tier 1, read once per
  // proposal and cached per request); a teaser that cannot be read leaves its cards without a band.
  const ids = [...new Set(items.map((item) => item.proposal_id))];
  const teasers = await Promise.all(ids.map((id) => getTeaser(id).catch(() => null)));
  const nicheOf = new Map(ids.map((id, index) => [id, teasers[index]?.teaser.niche ?? null]));
  // The assignee's quiet line on each card (never a chip: docs/spec/07 item 2's two stay the stage and the turn).
  const assignees = new Map(
    await Promise.all(items.map(async (item) => [item.id, await assigneeLine(item.team, userId)] as const)),
  );
  // The app clock's instant (the API's X-App-Now): every card's live clock counts from it.
  const now = appNow();
  const waiting = items.filter((item) => awaitsMe(item, "org"));
  const rest = items.filter((item) => !awaitsMe(item, "org"));
  const groups = [
    { key: "needs", title: t("needsUs"), items: waiting },
    { key: "rest", title: t("others"), items: rest },
  ].filter((group) => group.items.length > 0);
  // `first`: the first group drawn; its first card's band is the page's largest picture, fetched at once.
  const grid = (list: OrgSummary[], level: 2 | 3, group: string, first: boolean, label?: string) => (
    // As many 20 rem columns as fit, sharing the width, as the developer's list.
    <ul
      aria-label={label}
      data-group={label ? group : undefined}
      className="grid gap-4 sm:grid-cols-[repeat(auto-fit,minmax(20rem,1fr))]"
    >
      {list.map((item, i) => (
        <li key={item.id} className="cv-auto flex min-w-0 [--cv-size:16rem] [&>article]:flex-1">
          <EngagementCard
            eager={first && i === 0}
            item={item}
            mine="org"
            headingLevel={level}
            href={`${ENGAGEMENTS_PATH}/${encodeURIComponent(item.id)}${query}`}
            niche={nicheOf.get(item.proposal_id) ?? null}
            now={now}
            assignee={assignees.get(item.id) ?? null}
          />
        </li>
      ))}
    </ul>
  );
  if (groups.length === 1) return grid(groups[0].items, 2, groups[0].key, true, groups[0].title);
  return (
    <div className="flex flex-col gap-12 lg:gap-14">
      {groups.map((group, gi) => (
        <Section key={group.key} title={group.title} headingId={`engagements-${group.key}`} data-group={group.key}>
          {grid(group.items, 3, group.key, gi === 0)}
        </Section>
      ))}
    </div>
  );
}
