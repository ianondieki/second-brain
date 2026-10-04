import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { ClientStrings } from "@/components/ClientStrings";
import { OrgNav } from "@/components/OrgNav";
import { SignedInShell } from "@/components/SignedInShell";
import { buttonClass } from "@/components/ui/Button";
import { PageHeader } from "@/components/ui/PageHeader";
import { Section } from "@/components/ui/Section";
import type { Me } from "@/lib/auth/routing";
import { clientStrings } from "@/lib/i18n/client-strings";

import { getTeaser, orgContext } from "../../../data";
import { EmptyState } from "@/components/ui/EmptyState";
import { OrgRefusal } from "../../../OrgRefusal";
import { engagementsHref, type Membership } from "../../../membership";
import { interestReasonOf, matchesHref, type MatchDetail } from "../../../scout";
import { getMatch, getMembers, type Member } from "../../../scout-data";
import { TeaserDetails } from "../../[proposalId]/TeaserDetails";
import { FitMeter, Why } from "../MatchParts";
import { ExpressInterest } from "./ExpressInterest";
import { StandaloneLink } from "@/components/ui/StandaloneLink";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("scoutMatch");
  return { title: t("pageTitle"), robots: { index: false } };
}

/**
 * Organisation › Inbox › a scout match (REQ-SCOUT-02, REQ-ENG-04; the EM3 digest links here): the public teaser with
 * the developer's pseudonymous handle, why the scout matched it, and Express interest, the one primary action, for a
 * signatory of an E2 organisation. When it is not offered, the reason is a fixed sentence. Reading this page changes
 * nothing (docs/spec/06 6.8: nothing changes state on GET).
 */
export default async function MatchScreen({ params, searchParams }: PageProps<"/org/inbox/matches/[matchId]">) {
  const [{ matchId }, query] = await Promise.all([params, searchParams]);
  const { me, memberships, org, missing, query: orgParam } = await orgContext(query.org);
  const t = await getTranslations("scoutMatch");
  const ti = await getTranslations("inbox");
  const tm = await getTranslations("scoutMatches");
  const nav = <OrgNav current="inbox" query={orgParam} />;
  const back = org ? matchesHref(memberships, org.org_id) : "/org/inbox?tab=matches";
  const found = org ? await getMatch(org.org_id, matchId) : null;


  if (!org || !found || found.kind === "refused" || !found.value.available || !found.value.teaser) {
    let body;
    if (!org) {
      body =
        missing === "notMember" ? (
          <EmptyState sentence={ti("notMember")} action={ti("openOwnInbox")} href="/org/inbox" />
        ) : (
          <EmptyState sentence={ti("noOrg")} action={ti("emptyAction")} href="/org" />
        );
    } else if (found?.kind === "refused") {
      body = <OrgRefusal refusal={found.refusal} orgName={org.org_name} back={{ href: back, action: t("back") }} />;
    } else if (found?.kind === "ok") {
      body = <EmptyState sentence={t("unavailable")} action={t("back")} href={back} />;
    } else {
      body = <EmptyState sentence={t("notFound")} action={t("back")} href={back} />;
    }
    return (
      <SignedInShell homeHref={`/org${orgParam}`} nav={nav}>
        <PageHeader back={{ href: back, label: t("back") }} title={t("pageTitle")} />
        <div className="mt-6">{body}</div>
      </SignedInShell>
    );
  }

  const match = found.value;
  const teaser = match.teaser!;
  // The match is the organisation's (read above): its teaser and, when Express interest is offered, the reviewer
  // seats it can name are read together.
  const offered = interestReasonOf(match.interest) === null;
  const [card, members] = await Promise.all([
    getTeaser(match.proposal_id),
    offered ? getMembers(org.org_id) : Promise.resolve(null),
  ]);
  // The handle shows once: in the teaser's details when they load, else here under the title.
  return (
    <SignedInShell homeHref={`/org${orgParam}`} nav={nav} wide>
      <article className="flex max-w-3xl flex-col gap-12" data-match={match.id}>
        {/* One flex item: the back link sits on the title, not a column gap away. */}
        <div>
          <PageHeader
            back={{ href: back, label: t("back") }}
            title={teaser.title ?? ti("untitled")}
            lead={
              match.owner_handle || match.niche ? (
                <>
                  {match.owner_handle && !card ? (
                    <span className="block" data-owner-handle="">
                      {tm("by", { handle: match.owner_handle })}
                    </span>
                  ) : null}
                  {match.niche ? <span className="block">{match.niche.label}</span> : null}
                </>
              ) : undefined
            }
          >
            {/* The fit under the title, not a label above it. */}
            <p className="mt-3">
              <FitMeter score={match.score} />
            </p>
          </PageHeader>
        </div>
        <Why match={match} heading />
        {card ? <TeaserDetails card={card} /> : null}
        <Interest match={match} memberships={memberships} org={org} query={orgParam} me={me} members={members} />
      </article>
    </SignedInShell>
  );
}

/** Express interest, or the fixed reason it is not offered (a signatory of an E2 organisation only). */
async function Interest({
  match,
  memberships,
  org,
  query,
  me,
  members,
}: {
  match: MatchDetail;
  memberships: Membership[];
  org: Membership;
  /** "?org=<id>" for members of several organisations, kept on the tracker link. */
  query: string;
  me: Me;
  /** The organisation's members when Express interest is offered (null: not offered, or they could not be read). */
  members: Member[] | null;
}) {
  const t = await getTranslations("scoutMatch");
  const tx = await getTranslations("expressInterest");
  const reason = interestReasonOf(match.interest);
  const tracker = match.engagement_id ? engagementsHref(memberships, org.org_id, match.engagement_id) : null;
  return (
    <Section title={t("interestTitle")} headingId="interest-heading" description={t("interestLead")} data-interest="">
      {/* Offered, it is the step that needs the reader: a raised card. Not offered, the reason stays plain text. */}
      <div className={reason === null ? "rounded-panel border border-line bg-field p-5 shadow-card sm:p-7" : undefined}>
        {reason === null ? (
          <ClientStrings strings={await clientStrings(["expressInterest", "trackerActions"])}>
            <ExpressInterest
              orgId={org.org_id}
              orgName={org.org_name}
              matchId={match.id}
              proposalId={match.proposal_id}
              members={members?.map((m) => ({ user_id: m.user_id, display_name: m.display_name })) ?? null}
              myUserId={me.user.id}
              enrolled={me.mfa.enrolled}
              query={query}
              today={match.today ?? null}
            />
          </ClientStrings>
        ) : (
          <div className="flex flex-col items-start gap-3" data-interest-reason={reason ?? ""}>
            {reason !== "engagement_exists" ? (
              // docs/spec/06 6.8: the button shows, disabled, with the reason it cannot be used. aria-disabled keeps
              // it focusable, so a keyboard or screen-reader user reaches it and hears the reason.
              <button
                type="button"
                aria-disabled="true"
                aria-describedby="interest-reason"
                data-interest-disabled=""
                className={buttonClass(
                  "secondary",
                  "w-full cursor-not-allowed border-line text-ink-soft hover:bg-transparent sm:w-auto",
                )}
              >
                {tx("button")}
              </button>
            ) : null}
            <p id="interest-reason" className="max-w-[62ch] text-ink">
              {t(`reason.${reason ?? "other"}`, { org: org.org_name })}
            </p>
            {tracker ? (
              <StandaloneLink href={tracker}>
                {t("openTracker")}
              </StandaloneLink>
            ) : null}
          </div>
        )}
      </div>
    </Section>
  );
}
