import type { Metadata } from "next";
import Link from "next/link";
import { getLocale, getTranslations } from "next-intl/server";

import { OrgNav } from "@/components/OrgNav";
import { SignedInShell } from "@/components/SignedInShell";
import { titleLinkClass } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { StandaloneLink } from "@/components/ui/StandaloneLink";

import { orgContext } from "../../data";
import { formatDay } from "../../format";
import { first, inboxHref, proposalHref, type Membership } from "../../membership";
import { OrgPicker } from "../../OrgPicker";
import { OrgRefusal } from "../../OrgRefusal";
import { matchesHref } from "../../scout";
import {
  COMPARE_MAX,
  COMPARE_MIN,
  COMPARE_PATH,
  compareAction,
  editsShortlist,
  shortlistHref,
  type ShortlistEntry,
  type ShortlistProblem,
  type ShortlistPage,
} from "../../shortlist";
import { getShortlist } from "../../shortlist-data";
import { InboxTabs } from "../InboxTabs";
import { CompareBar } from "./CompareBar";
import { RemoveEntry } from "./RemoveEntry";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("shortlist");
  return { title: t("pageTitle") };
}

const CURSOR = /^[A-Za-z0-9_-]{1,500}$/;
const PROBLEMS: readonly ShortlistProblem[] = ["code", "signedOut", "role", "gone", "network", "failed"];

/**
 * Organisation › Inbox › Shortlist (REQ-REPO-02, P21 track B): the proposals the organisation's people starred, shared
 * by every member, newest first, each saying who added it and when. Tick 2 to 4 and Compare (the one primary action)
 * opens their public facts side by side. Reviewers, signatories and admins remove entries; one that is no longer
 * available says so and can only be removed.
 */
export default async function ShortlistScreen({ searchParams }: PageProps<"/org/inbox/shortlist">) {
  const params = await searchParams;
  const { memberships, org, missing, query } = await orgContext(params.org);
  const t = await getTranslations("inbox");
  const cursorParam = first(params.cursor);
  const cursor = cursorParam && CURSOR.test(cursorParam) ? cursorParam : undefined;

  return (
    <SignedInShell homeHref={`/org${query}`} nav={<OrgNav current="inbox" query={query} />} wide>
      <div className="max-w-3xl">
        <PageHeader title={t("title")} />
        {org ? (
          <>
            <InboxTabs
              current="shortlist"
              hrefs={{
                tagged: inboxHref(memberships, org.org_id),
                matches: matchesHref(memberships, org.org_id),
                shortlist: shortlistHref(memberships, org.org_id),
              }}
            />
            <ShortlistBody memberships={memberships} org={org} cursor={cursor} />
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

async function ShortlistBody({ memberships, org, cursor }: { memberships: Membership[]; org: Membership; cursor?: string }) {
  const t = await getTranslations("shortlist");
  const ti = await getTranslations("inbox");
  const result = await getShortlist(org.org_id, cursor);
  const newest = shortlistHref(memberships, org.org_id);

  let body;
  if (result.kind === "refused") {
    body = (
      <OrgRefusal refusal={result.refusal} orgName={org.org_name} back={{ href: "/org", action: ti("emptyAction") }} />
    );
  } else if (result.kind === "staleCursor" || (result.page.items.length === 0 && cursor)) {
    body = <EmptyState sentence={t("staleCursor")} action={ti("newestPage")} href={newest} />;
  } else if (result.page.items.length === 0) {
    body = (
      <EmptyState
        sentence={editsShortlist(org) ? t("empty") : t("emptyReader", { org: org.org_name })}
        action={t("emptyAction")}
        href={inboxHref(memberships, org.org_id)}
      />
    );
  } else {
    body = <Entries page={result.page} memberships={memberships} org={org} cursor={cursor} newest={newest} />;
  }

  return (
    <>
      <p className="mt-6 max-w-[62ch] text-ink-soft">{t("lead", { org: org.org_name })}</p>
      {memberships.length > 1 ? (
        <div className="mt-6">
          <OrgPicker memberships={memberships} current={org.org_id} action="/org/inbox/shortlist" />
        </div>
      ) : null}
      <div className="mt-8">{body}</div>
    </>
  );
}

async function Entries({
  page,
  memberships,
  org,
  cursor,
  newest,
}: {
  page: ShortlistPage;
  memberships: Membership[];
  org: Membership;
  cursor?: string;
  newest: string;
}) {
  const t = await getTranslations("shortlist");
  const ti = await getTranslations("inbox");
  const available = page.items.filter((entry) => entry.available).length;
  const comparable = available >= COMPARE_MIN;
  const multi = memberships.length > 1;
  return (
    // A GET form: without script it opens the compare page with the ticked ids (CompareBar shortens the address).
    <form method="get" action={COMPARE_PATH} aria-label={t("formLabel")}>
      {multi ? <input type="hidden" name="org" value={org.org_id} /> : null}
      {/* tabIndex -1: Remove moves focus here once its row leaves the list. */}
      <ul aria-label={t("listLabel", { org: org.org_name })} tabIndex={-1} data-shortlist-list="" className="flex flex-col focus:outline-none">
        {page.items.map((entry) => (
          <li key={entry.proposal_id}>
            <EntryRow entry={entry} memberships={memberships} org={org} selectable={comparable} />
          </li>
        ))}
      </ul>
      <div className="mt-6 border-t border-line pt-6">
        {comparable ? (
          <CompareBar
            action={compareAction(memberships, org.org_id)}
            labels={{
              compare: t("compare"),
              chosen: t("chosen", { count: "{count}", max: COMPARE_MAX }),
              hint: t("compareHint", { min: COMPARE_MIN, max: COMPARE_MAX }),
              tooFew: t("tooFew", { min: COMPARE_MIN }),
              tooMany: t("tooMany", { max: COMPARE_MAX }),
            }}
          />
        ) : (
          <p className="text-sm text-ink-soft">{t("needTwo")}</p>
        )}
      </div>
      {cursor || page.next_cursor ? (
        <nav aria-label={t("pages")} className="mt-8 flex flex-wrap items-center justify-between gap-x-8 gap-y-2">
          {cursor ? <StandaloneLink href={newest}>{ti("newestPage")}</StandaloneLink> : <span />}
          {page.next_cursor ? (
            <StandaloneLink href={shortlistHref(memberships, org.org_id, page.next_cursor)}>{t("older")}</StandaloneLink>
          ) : null}
        </nav>
      ) : null}
    </form>
  );
}

/**
 * One entry: a box to choose it for Compare, the title (a link to the proposal page), its niche and who added it
 * when, and Remove for those who may change the shortlist. An entry no longer available says so, without a title.
 */
async function EntryRow({
  entry,
  memberships,
  org,
  selectable,
}: {
  entry: ShortlistEntry;
  memberships: Membership[];
  org: Membership;
  selectable: boolean;
}) {
  const t = await getTranslations("shortlist");
  const ti = await getTranslations("inbox");
  const locale = await getLocale();
  const title = entry.available ? (entry.title ?? ti("untitled")) : t("unavailable");
  const titleId = `entry-${entry.proposal_id}`;
  const problem = Object.fromEntries(PROBLEMS.map((key) => [key, t(`problem.${key}`)])) as Record<ShortlistProblem, string>;
  return (
    <article
      data-shortlist-entry={entry.proposal_id}
      data-available={entry.available ? "true" : "false"}
      aria-labelledby={titleId}
      className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-start gap-x-3 border-t border-line py-5 sm:gap-x-4"
    >
      {selectable && entry.available ? (
        // The whole 44 px square is the box's target (WCAG 2.5.8), not only the 20 px box.
        <label className="-mt-2.5 -ml-2.5 flex size-11 cursor-pointer items-center justify-center">
          <input
            type="checkbox"
            name="ids"
            value={entry.proposal_id}
            aria-label={t("choose", { title })}
            className="size-5 cursor-pointer accent-accent"
          />
        </label>
      ) : (
        <span className="-mt-2.5 -ml-2.5 size-11" />
      )}
      <div className="flex min-w-0 flex-col gap-1.5">
        <h2 id={titleId} className="text-base font-semibold [overflow-wrap:anywhere] text-ink">
          {entry.available ? (
            <Link href={proposalHref(memberships, org.org_id, entry.proposal_id)} className={titleLinkClass}>
              {title}
            </Link>
          ) : (
            <span className="text-ink-soft">{title}</span>
          )}
        </h2>
        <p className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-ink-soft">
          {entry.available && entry.niche ? <span>{entry.niche.label}</span> : null}
          <span data-added-by="">
            {t("addedBy", { name: entry.added_by_name, date: formatDay(locale, entry.added_at) })}
          </span>
        </p>
        {entry.available ? null : <p className="max-w-[62ch] text-sm text-ink">{t("unavailableNote")}</p>}
      </div>
      {editsShortlist(org) ? (
        <RemoveEntry
          orgId={org.org_id}
          proposalId={entry.proposal_id}
          labels={{ remove: t("removeEntry"), name: t("removeNamed", { title }), busy: t("removing"), problem }}
        />
      ) : (
        <span />
      )}
    </article>
  );
}
