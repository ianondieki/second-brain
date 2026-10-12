import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { OrgNav } from "@/components/OrgNav";
import { OfflineSlot } from "@/components/offline/OfflineSlot";
import { SignedInShell } from "@/components/SignedInShell";
import { orgEngagements } from "@/components/tracker/data";
import { EngagementCard } from "@/components/engagements/EngagementCard";
import { AssigneeFilter, assignedToMe, assigneeLine, isAssignedTo } from "@/components/team/AssigneeFilter";
import { awaitsMe, type OrgSummary } from "@/components/tracker/model";
import { Section } from "@/components/ui/Section";
import { appNow } from "@/lib/api/server";

import { getTeaser, orgContext } from "../data";
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
      offline={<OfflineSlot page={(await getTranslations("nav"))("engagements")} />}
    >
      <div className="max-w-5xl">
        <PageHero eyebrow={tp("eyebrow.engagements")} title={t("title")} lead={org ? t("orgLead") : undefined} />
        {org ? (
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
  const filter =
    read.ok && read.value.length > 0 ? (
      <AssigneeFilter
        mine={mine}
        allHref={allHref}
        mineHref={`${ENGAGEMENTS_PATH}${orgQuery(memberships, org.org_id, { assignee: "me" })}`}
        className="mb-6"
      />
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
    body = <EngagementGrid items={shown} query={query} userId={userId} />;
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
