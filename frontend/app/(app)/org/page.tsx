import type { Metadata } from "next";
import { cookies } from "next/headers";
import Link from "next/link";
import { unstable_rethrow } from "next/navigation";
import { getLocale, getTranslations } from "next-intl/server";

import { ClientStrings } from "@/components/ClientStrings";
import { OrgNav } from "@/components/OrgNav";
import { SignedInShell } from "@/components/SignedInShell";
import { FirstLoginTour } from "@/components/tour/FirstLoginTour";
import { tourDoneFromCookies } from "@/components/tour/tour-store";
import { orgEngagements } from "@/components/tracker/data";
import { NeedsYouCard } from "@/components/tracker/NeedsYouCard";
import { standaloneLinkClass } from "@/components/ui/Button";
import { ButtonLink } from "@/components/ui/ButtonLink";
import { Callout } from "@/components/ui/Callout";
import { CardGrid } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { Section } from "@/components/ui/Section";
import { StatTile } from "@/components/ui/StatTile";
import { AlertIcon, CheckIcon, InfoIcon } from "@/components/ui/status-icons";
import { needsMfaSetup } from "@/lib/auth/routing";
import { clientStrings } from "@/lib/i18n/client-strings";

import { getBriefs } from "./brief-data";
import { briefStats, problemsHref } from "./briefs";
import { getInbox, orgContext, type InboxPage } from "./data";
import { formatDay } from "./format";
import { orgHomeStats, weeklySeries } from "./home";
import { InboxCard } from "./inbox/InboxCard";
import { engagementsHref, inboxHref, proposalHref, type Membership } from "./membership";
import { matchesHref, type Match } from "./scout";
import { getMatches } from "./scout-data";

/** How many Inbox proposals Home shows before "All proposals". */
const INBOX_SHOWN = 4;

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("home");
  return { title: t("orgPageTitle") };
}

/**
 * Organisation home (docs/spec/07 item 1; D-52): the greeting, four stat tiles from the Inbox, the scout's matches,
 * the engagements and the Problem Briefs (with a sparkline where a series exists), two-step sign-in as a notice only
 * while it is off, what needs the organisation as prominent cards, then the newest Inbox proposals as compact cards.
 * "Open the Inbox" is the screen's one primary action; an owner without two-step sign-in gets "Turn on" instead,
 * since the Inbox is refused until then.
 */
export default async function OrganisationHome({ searchParams }: PageProps<"/org">) {
  const { me, memberships, org, missing, query } = await orgContext((await searchParams).org);
  const t = await getTranslations("home");
  const ti = await getTranslations("inbox");
  const setupNeeded = needsMfaSetup(me.mfa);
  const mfa = me.mfa.enrolled ? "on" : setupNeeded ? "required" : "off";
  const ready = org !== null && !setupNeeded;

  return (
    <SignedInShell homeHref={`/org${query}`} nav={<OrgNav current="home" query={query} />} wide>
      <ClientStrings strings={await clientStrings(["tour"])}>
        <FirstLoginTour side="org" initialDone={tourDoneFromCookies(await cookies(), "org")} />
      </ClientStrings>
      <div className="max-w-4xl">
        <PageHeader
          title={t("title", { name: me.user.display_name })}
          lead={org ? t("orgLead", { org: org.org_name }) : t("orgLeadNoName")}
          action={
            setupNeeded ? (
              <ButtonLink href="/settings/security" variant="primary">
                {t("turnOn")}
              </ButtonLink>
            ) : org ? (
              <ButtonLink href={inboxHref(memberships, org.org_id)} variant="primary">
                {(await getTranslations("orgHome"))("open")}
              </ButtonLink>
            ) : undefined
          }
        />
      </div>

      <div className="mt-8 flex max-w-4xl flex-col gap-12">
        {/* Two-step sign-in: one quiet line when it is on (the confirmation after turning it on), a notice while off. */}
        {mfa === "on" ? (
          <p className="-mt-6 flex items-center gap-2 text-sm text-ink-soft" data-home="security">
            <CheckIcon className="size-4 shrink-0 text-ok" />
            {t("mfaOn")}
          </p>
        ) : (
          <Callout
            tone={mfa === "required" ? "error" : "info"}
            icon={mfa === "required" ? <AlertIcon className="mt-0.5 size-5 shrink-0 text-error" /> : <InfoIcon className="mt-0.5 size-5 shrink-0 text-accent" />}
            data-home="security"
          >
            <p>{mfa === "required" ? t("mfaRequired") : t("mfaOff")}</p>
            <Link href="/settings/security" className={standaloneLinkClass}>
              {t("setUp")}
            </Link>
          </Callout>
        )}

        {missing === "notMember" ? <EmptyState sentence={ti("notMember")} action={ti("openOwnInbox")} href="/org/inbox" /> : null}

        {/* The Inbox asks for two-step sign-in first (the API refuses it before then), so it waits for the setup. */}
        {ready ? <HomeBody memberships={memberships} org={org} /> : null}
      </div>
    </SignedInShell>
  );
}

/** A stat tile draws its sparkline from this many items on (fewer make a hockey stick with no scale). */
const SPARK_FROM = 5;

/** Reads one list for Home; the home never becomes the error page, so a failed read shows "could not be read" for that list. */
async function quietly<T>(read: () => Promise<T>): Promise<T | null> {
  try {
    return await read();
  } catch (error) {
    unstable_rethrow(error); // a redirect (the session ended) still happens
    return null;
  }
}

async function HomeBody({ memberships, org }: { memberships: Membership[]; org: Membership }) {
  const [t, ti, tt, locale] = await Promise.all([getTranslations("orgHome"), getTranslations("inbox"), getTranslations("tracker"), getLocale()]);
  const [inboxRead, matchesRead, engagementsRead, briefsRead] = await Promise.all([
    quietly(() => getInbox(org.org_id)),
    quietly(() => getMatches(org.org_id)),
    quietly(() => orgEngagements(org.org_id)),
    quietly(() => getBriefs(org.org_id)),
  ]);
  const inbox: InboxPage | null = inboxRead?.kind === "page" ? inboxRead.page : null;
  const matches: Match[] | null = matchesRead?.kind === "ok" ? matchesRead.value : null;
  const engagements = engagementsRead?.ok ? engagementsRead.value : null;
  const stats = orgHomeStats(inbox, matches, engagements);
  const briefs = briefsRead?.kind === "ok" ? briefStats(briefsRead.value) : null;
  const now = new Date();
  const inboxLink = inboxHref(memberships, org.org_id);
  const engagementsLink = engagementsHref(memberships, org.org_id);

  const [newest] = inbox?.items ?? [];
  // A tile whose list could not be read says so instead of a figure (never a confident zero).
  const unknown = { value: t("stats.unknown"), meta: t("stats.unavailable") };
  const inboxSentence = inbox
    ? newest
      ? t("newest", { title: newest.proposal.teaser.title ?? ti("untitled"), date: formatDay(locale, newest.pitched_at) })
      : inbox.held_count > 0
        ? ti("held", { count: inbox.held_count, org: org.org_name })
        : ti(inbox.verification === "e2" ? "emptyE2" : inbox.verification === "e1" ? "emptyE1" : "emptyUnverified", { org: org.org_name })
    : null;

  return (
    <>
      <section aria-label={t("stats.label")} data-home="stats">
        <ul className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
          <li>
            <StatTile
              data-stat="inbox"
              label={t("stats.inbox")}
              value={stats.inbox === null ? unknown.value : stats.more ? t("stats.more", { count: stats.inbox }) : stats.inbox}
              meta={stats.inbox === null ? unknown.meta : stats.inbox === 0 ? undefined : stats.fresh > 0 ? t("stats.inboxMeta", { count: stats.fresh }) : t("stats.inboxMetaNone")}
              // A series only once it can show a shape: under five points it is a hockey stick with no scale.
              spark={inbox && stats.inbox !== null && stats.inbox >= SPARK_FROM ? weeklySeries(inbox.items.map((item) => item.pitched_at), now) : undefined}
              href={inboxLink}
            />
          </li>
          <li>
            <StatTile
              data-stat="matches"
              label={t("stats.matches")}
              value={stats.matches === null ? unknown.value : stats.matches}
              meta={stats.matches === null ? unknown.meta : stats.newestMatch ? t("stats.matchesMeta", { date: formatDay(locale, stats.newestMatch) }) : undefined}
              spark={matches && stats.matches !== null && stats.matches >= SPARK_FROM ? weeklySeries(matches.map((match) => match.created_at), now) : undefined}
              href={matchesHref(memberships, org.org_id)}
            />
          </li>
          <li>
            <StatTile
              data-stat="engagements"
              label={t("stats.engagements")}
              value={stats.engagements === null ? unknown.value : stats.engagements}
              meta={stats.engagements === null ? unknown.meta : t("stats.engagementsMeta", { count: stats.active })}
              href={engagementsLink}
            />
          </li>
          {/* The fourth tile is the Problem Briefs (REQ-DIR-05), in place of "Need us": the engagements waiting on the
              organisation are the cards right below, so that tile only repeated them, and it led nowhere. */}
          <li>
            <StatTile
              data-stat="briefs"
              label={t("stats.briefs")}
              value={briefs === null ? unknown.value : t("stats.briefsValue", { count: briefs.open })}
              meta={
                briefs === null
                  ? unknown.meta
                  : briefs.inReview > 0
                    ? t("stats.briefsMetaReview", { count: briefs.inReview })
                    : briefs.open > 0
                      ? t("stats.briefsMetaProposals", { count: briefs.proposals })
                      : undefined
              }
              href={problemsHref(memberships, org.org_id)}
            />
          </li>
        </ul>
      </section>

      {stats.waiting.length > 0 ? (
        <Section title={tt("needsUs")} headingId="home-needs-us" data-home="needs-us">
          <ul className="flex flex-col gap-4">
            {stats.waiting.map((item) => (
              <li key={item.id}>
                <NeedsYouCard item={item} mine="org" href={engagementsHref(memberships, org.org_id, item.id)} action={t("openTracker")} />
              </li>
            ))}
          </ul>
        </Section>
      ) : null}

      <Section
        title={t("inboxTitle")}
        headingId="home-inbox"
        data-home="inbox"
        description={inboxSentence}
        link={newest ? { href: inboxLink, label: t("allProposals") } : undefined}
      >
        {newest ? (
          <CardGrid>
            {inbox!.items.slice(0, INBOX_SHOWN).map((item) => (
              <li key={item.tag_id}>
                <InboxCard item={item} href={proposalHref(memberships, org.org_id, item.proposal.id)} />
              </li>
            ))}
          </CardGrid>
        ) : null}
      </Section>
    </>
  );
}
