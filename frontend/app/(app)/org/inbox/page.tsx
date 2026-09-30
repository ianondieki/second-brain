import type { Metadata } from "next";
import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { OrgNav } from "@/components/OrgNav";
import { SignedInShell } from "@/components/SignedInShell";
import { standaloneLinkClass } from "@/components/ui/Button";

import { getInbox, orgContext, type InboxPage, type OrgVerification } from "../data";
import { EmptyState } from "@/components/ui/EmptyState";
import { engagementsHref, first, inboxHref, proposalHref, type Membership } from "../membership";
import { OrgPicker } from "../OrgPicker";
import { ACTION_HREF } from "../refusals";
import { matchesHref } from "../scout";
import { InboxRow } from "./InboxRow";
import { InboxTabs, inboxTab } from "./InboxTabs";
import { ScoutMatches } from "./matches/ScoutMatches";

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
  const { memberships, org, missing, query } = await orgContext(params.org);
  const t = await getTranslations("inbox");
  const cursorParam = first(params.cursor);
  const cursor = cursorParam && CURSOR.test(cursorParam) ? cursorParam : undefined;
  const tab = inboxTab(first(params.tab));

  return (
    <SignedInShell homeHref={`/org${query}`} nav={<OrgNav current="inbox" query={query} />} wide>
      <div className="max-w-3xl">
        <h1 className="text-xl text-ink lg:text-2xl">{t("title")}</h1>
        {org ? (
          <>
            <InboxTabs
              current={tab}
              hrefs={{ tagged: inboxHref(memberships, org.org_id), matches: matchesHref(memberships, org.org_id) }}
            />
            {tab === "matches" ? (
              <ScoutMatches memberships={memberships} org={org} />
            ) : (
              <InboxBody memberships={memberships} org={org} cursor={cursor} />
            )}
          </>
        ) : (
          <div className="mt-6">
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
}: {
  memberships: Membership[];
  org: Membership;
  cursor?: string;
}) {
  const t = await getTranslations("inbox");
  const tp = await getTranslations("orgProposal");
  const orgName = org.org_name;
  const result = await getInbox(org.org_id, cursor);
  const newest = inboxHref(memberships, org.org_id);

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
    body = <InboxList page={result.page} memberships={memberships} org={org} cursor={cursor} newest={newest} />;
  }

  return (
    <>
      <p className="mt-6 max-w-[62ch] text-ink-soft">{t("lead", { org: orgName })}</p>
      {memberships.length > 1 ? (
        <div className="mt-6">
          <OrgPicker memberships={memberships} current={org.org_id} action="/org/inbox" />
        </div>
      ) : null}
      <div className="mt-8">{body}</div>
    </>
  );
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
}: {
  page: InboxPage;
  memberships: Membership[];
  org: Membership;
  cursor?: string;
  newest: string;
}) {
  const t = await getTranslations("inbox");
  const orgName = org.org_name;
  const held =
    page.held_count > 0 ? (
      <p data-held-count={page.held_count} className="mb-6 max-w-[62ch] border-l-2 border-jacaranda pl-3 text-ink">
        {t("held", { count: page.held_count, org: orgName })}
      </p>
    ) : null;

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
      <section aria-label={t("listLabel", { org: orgName })}>
        {page.items.map((item) => (
          <InboxRow
            key={item.tag_id}
            item={item}
            href={proposalHref(memberships, org.org_id, item.proposal.id)}
            trackerHref={item.engagement ? engagementsHref(memberships, org.org_id, item.engagement.id) : undefined}
          />
        ))}
      </section>
      {cursor || page.next_cursor ? (
        <nav aria-label={t("pages")} className="mt-8 flex flex-wrap items-center justify-between gap-x-8 gap-y-2">
          {cursor ? (
            <Link href={newest} className={standaloneLinkClass}>
              {t("newestPage")}
            </Link>
          ) : (
            <span />
          )}
          {page.next_cursor ? (
            <Link href={inboxHref(memberships, org.org_id, page.next_cursor)} className={standaloneLinkClass}>
              {t("older")}
            </Link>
          ) : null}
        </nav>
      ) : null}
    </>
  );
}
