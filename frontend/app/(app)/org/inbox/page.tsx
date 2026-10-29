import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { OrgNav } from "@/components/OrgNav";
import { SignedInShell } from "@/components/SignedInShell";
import { Callout } from "@/components/ui/Callout";
import { NicheBand } from "@/components/ui/NicheBand";
import { PageHero } from "@/components/ui/PageHero";

import { getInbox, INBOX_MAX_PAGE, orgContext, type InboxPage, type OrgVerification } from "../data";
import { EmptyState } from "@/components/ui/EmptyState";
import { engagementsHref, first, INBOX_PATH, inboxHref, orgQuery, proposalHref, type Membership } from "../membership";
import { OrgPicker } from "../OrgPicker";
import { ACTION_HREF } from "../refusals";
import { matchesHref } from "../scout";
import { shortlistHref } from "../shortlist";
import { CARD_BAND, ItemGrid } from "../ItemCard";
import { InboxRow } from "./InboxRow";
import { InboxTabs, inboxTab } from "./InboxTabs";
import { ScoutMatches } from "./matches/ScoutMatches";
import { StandaloneLink } from "@/components/ui/StandaloneLink";
import { AssigneeFilter, assignedToMe, assigneeLine, isAssignedTo } from "@/components/team/AssigneeFilter";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("inbox");
  return { title: t("pageTitle") };
}

// Keyset cursors are the API's own (URL-safe base64); anything else is dropped before it reaches the API.
const CURSOR = /^[A-Za-z0-9_-]{1,500}$/;

/**
 * Organisation › Inbox (REQ-PROP-03, F4): the proposals developers sent to this organisation, newest first, as
 * Tier-1 teasers from GET /api/orgs/{org_id}/inbox, rendered on the server. An E1 organisation sees only how many
 * wait for its verification. Members of several organisations pick one.
 */
export default async function InboxScreen({ searchParams }: PageProps<"/org/inbox">) {
  const params = await searchParams;
  const { me, memberships, org, missing, query } = await orgContext(params.org);
  const mine = assignedToMe(params.assignee);
  const [t, tm, tp25] = await Promise.all([getTranslations("inbox"), getTranslations("scoutMatches"), getTranslations("portal")]);
  const cursorParam = first(params.cursor);
  const cursor = cursorParam && CURSOR.test(cursorParam) ? cursorParam : undefined;
  const tab = inboxTab(first(params.tab));

  return (
    <SignedInShell homeHref={`/org${query}`} nav={<OrgNav current="inbox" query={query} />} wide>
      <div className="max-w-5xl">
        <PageHero
          eyebrow={tp25("eyebrow.inbox")}
          title={t("title")}
          lead={org ? (tab === "matches" ? tm("lead", { org: org.org_name }) : t("lead", { org: org.org_name })) : undefined}
          tabs={
            org ? (
              <InboxTabs
                current={tab}
                hrefs={{
                  tagged: inboxHref(memberships, org.org_id),
                  matches: matchesHref(memberships, org.org_id),
                  shortlist: shortlistHref(memberships, org.org_id),
                }}
              />
            ) : undefined
          }
        />
        {org ? (
          <>
            {tab === "matches" ? (
              <ScoutMatches memberships={memberships} org={org} />
            ) : (
              <InboxBody memberships={memberships} org={org} cursor={cursor} mine={mine} userId={me.user.id} />
            )}
          </>
        ) : (
          <div>
            {missing === "notMember" ? (
              <EmptyState sentence={t("notMember")} action={t("openOwnInbox")} href="/org/inbox" />
            ) : (
              <EmptyState sentence={t("noOrg")} action={t("emptyAction")} href="/org" />
            )}
          </div>
        )}
      </div>
    </SignedInShell>
  );
}

async function InboxBody({
  memberships,
  org,
  cursor,
  mine,
  userId,
}: {
  memberships: Membership[];
  org: Membership;
  cursor?: string;
  /** "Assigned to me" (`?assignee=me`): the page's proposals whose engagement is assigned to the caller. */
  mine: boolean;
  userId: string;
}) {
  const t = await getTranslations("inbox");
  const tp = await getTranslations("orgProposal");
  const orgName = org.org_name;
  // Filtered, a page reads the API's largest page (50), so fewer pages hold nothing of the caller's.
  const result = await getInbox(org.org_id, cursor, mine ? INBOX_MAX_PAGE : undefined);
  const newest = mine ? inboxMineHref(memberships, org.org_id) : inboxHref(memberships, org.org_id);

  let body;
  if (result.kind === "staleCursor") {
    body = <EmptyState sentence={t("staleCursor")} action={t("newestPage")} href={newest} />;
  } else if (result.kind === "refused") {
    body =
      result.refusal === "mfa_enrolment_required" ? (
        <EmptyState
          sentence={t("refusedMfaSetup", { org: orgName })}
          action={tp("action.turnOnMfa")}
          href={ACTION_HREF.turnOnMfa!}
          primary
        />
      ) : result.refusal === "mfa_required" ? (
        <EmptyState
          sentence={t("refusedMfaCode")}
          action={tp("action.enterCode")}
          href={ACTION_HREF.enterCode!}
          primary
        />
      ) : (
        <EmptyState sentence={t("refusedNotFound")} action={t("emptyAction")} href="/org" />
      );
  } else {
    body = (
      <InboxList
        page={result.page}
        memberships={memberships}
        org={org}
        cursor={cursor}
        newest={newest}
        mine={mine}
        userId={userId}
      />
    );
  }

  return (
    <>
      {memberships.length > 1 ? (
        <div className="mb-6">
          <OrgPicker memberships={memberships} current={org.org_id} action="/org/inbox" />
        </div>
      ) : null}
      {body}
    </>
  );
}

/** The Inbox's "Assigned to me" view, optionally at a later page. */
function inboxMineHref(memberships: readonly Membership[], orgId: string, cursor?: string): string {
  return `${INBOX_PATH}${orgQuery(memberships, orgId, { assignee: "me", cursor })}`;
}

function emptySentence(verification: OrgVerification): "emptyE2" | "emptyE1" | "emptyUnverified" {
  if (verification === "e2") return "emptyE2";
  if (verification === "e1") return "emptyE1";
  return "emptyUnverified";
}

async function InboxList({
  page,
  memberships,
  org,
  cursor,
  newest,
  mine,
  userId,
}: {
  page: InboxPage;
  memberships: Membership[];
  org: Membership;
  cursor?: string;
  newest: string;
  mine: boolean;
  userId: string;
}) {
  const t = await getTranslations("inbox");
  const te = await getTranslations("engagements");
  const orgName = org.org_name;
  const allHref = inboxHref(memberships, org.org_id);
  const pageHref = (next: string) =>
    mine ? inboxMineHref(memberships, org.org_id, next) : inboxHref(memberships, org.org_id, next);
  const filter = (
    <AssigneeFilter mine={mine} allHref={allHref} mineHref={inboxMineHref(memberships, org.org_id)} className="mb-6" />
  );
  const items = mine ? page.items.filter((item) => isAssignedTo(item.engagement?.team, userId)) : page.items;
  // The assignee's quiet line in each card's meta (never a chip).
  const assignees = new Map(
    await Promise.all(
      items.map(async (item) => [item.tag_id, await assigneeLine(item.engagement?.team, userId)] as const),
    ),
  );
  const held =
    page.held_count > 0 ? (
      <Callout data-held-count={page.held_count} className="mb-6 max-w-[62ch]">
        <p>{t("held", { count: page.held_count, org: orgName })}</p>
      </Callout>
    ) : null;

  if (mine && items.length === 0) {
    // Nothing of the caller's here: on to the older page when there is one, else back to everything.
    return (
      <>
        {filter}
        {page.next_cursor ? (
          <EmptyState sentence={te("noneMineOnPage")} action={t("older")} href={pageHref(page.next_cursor)} />
        ) : (
          <EmptyState sentence={te("noneMine")} action={te("showAll")} href={allHref} />
        )}
      </>
    );
  }
  if (page.items.length === 0) {
    if (cursor) return <EmptyState sentence={t("staleCursor")} action={t("newestPage")} href={newest} />;
    // Held proposals are all an E1 organisation sees: their count is then the empty state's one sentence.
    const sentence =
      page.held_count > 0
        ? t("held", { count: page.held_count, org: orgName })
        : t(emptySentence(page.verification), { org: orgName });
    return <EmptyState sentence={sentence} action={t("emptyAction")} href="/org" />;
  }

  return (
    <>
      {held}
      {filter}
      <ItemGrid aria-label={t("listLabel", { org: orgName })}>
        {items.map((item) => (
          <li key={item.tag_id}>
            <InboxRow
              item={item}
              href={proposalHref(memberships, org.org_id, item.proposal.id)}
              trackerHref={item.engagement ? engagementsHref(memberships, org.org_id, item.engagement.id) : undefined}
              org={org}
              band={<NicheBand niche={item.proposal.teaser.niche?.slug} county={item.proposal.teaser.county_code} sizes={CARD_BAND} />}
              assignee={assignees.get(item.tag_id) ?? null}
            />
          </li>
        ))}
      </ItemGrid>
      {cursor || page.next_cursor ? (
        <nav aria-label={t("pages")} className="mt-8 flex flex-wrap items-center justify-between gap-x-8 gap-y-2">
          {cursor ? (
            <StandaloneLink href={newest}>
              {t("newestPage")}
            </StandaloneLink>
          ) : (
            <span />
          )}
          {page.next_cursor ? <StandaloneLink href={pageHref(page.next_cursor)}>{t("older")}</StandaloneLink> : null}
        </nav>
      ) : null}
    </>
  );
}
