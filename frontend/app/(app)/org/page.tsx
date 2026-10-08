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
import { tourScenes } from "@/components/tour/TourScenes";
import { orgEngagements } from "@/components/tracker/data";
import { NeedsYouCard } from "@/components/tracker/NeedsYouCard";
import { standaloneLinkClass } from "@/components/ui/Button";
import { ButtonLink } from "@/components/ui/ButtonLink";
import { Callout } from "@/components/ui/Callout";
import { EmptyState } from "@/components/ui/EmptyState";
import { NicheBand } from "@/components/ui/NicheBand";
import { Section } from "@/components/ui/Section";
import { StatTile } from "@/components/ui/StatTile";
import { AlertIcon, CheckIcon, InfoIcon } from "@/components/ui/status-icons";
import { ActivityCalendar } from "@/components/activity/ActivityCalendar";
import { WEEKS } from "@/components/activity/calendar";
import { getActivity } from "@/components/activity/fetch";
import { CountFigure } from "@/components/motion/CountFigure";
import { CountUp } from "@/components/motion/CountUp";
import { appNow } from "@/lib/api/server";
import { needsMfaSetup } from "@/lib/auth/routing";
import { clientStrings } from "@/lib/i18n/client-strings";

import { GreetingBand } from "../dev/GreetingBand";
import { dayPart } from "../dev/home";

import { getBriefs } from "./brief-data";
import { briefStats, problemsHref } from "./briefs";
import { getInbox, orgContext, type InboxPage } from "./data";
import { formatDay } from "./format";
import { orgHomeStats, weeklySeries } from "./home";
import { InboxCard } from "./inbox/InboxCard";
import { CARD_BAND, ItemGrid } from "./ItemCard";
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
 * Organisation home (docs/spec/07 item 1; D-52, D-67): the greeting by the time of day beside its Nairobi photograph,
 * four stat tiles (the Inbox, the scout's matches, the engagements, the Problem Briefs; a sparkline where a series
 * exists) whose figures count once, two-step sign-in as a notice only while it is off, "Your last 26 weeks" (this
 * person's own actions, the activity calendar), what needs the organisation as prominent cards, then the newest Inbox
 * proposals as cards under their niche's photograph. "Open the Inbox" is the screen's one primary action; an owner
 * without two-step sign-in gets "Turn on" instead, since the Inbox is refused until then.
 */
export default async function OrganisationHome({ searchParams }: PageProps<"/org">) {
  const { me, memberships, org, missing, query } = await orgContext((await searchParams).org);
  const [t, ti, tp] = await Promise.all([getTranslations("home"), getTranslations("inbox"), getTranslations("portal")]);
  // The greeting by the hour of the app clock in Nairobi (as on the developer's Home), with its photograph.
  const part = dayPart(appNow());
  const setupNeeded = needsMfaSetup(me.mfa);
  const mfa = me.mfa.enrolled ? "on" : setupNeeded ? "required" : "off";
  const ready = org !== null && !setupNeeded;

  const tourDone = tourDoneFromCookies(await cookies(), "org");
  return (
    <SignedInShell homeHref={`/org${query}`} nav={<OrgNav current="home" query={query} />} wide>
      <ClientStrings strings={await clientStrings(["tour"])}>
        <FirstLoginTour side="org" initialDone={tourDone} scenes={tourDone ? undefined : tourScenes("org")} />
      </ClientStrings>
      <div className="max-w-5xl">
        {/* The greeting on Nairobi at this time of day, the developer Home's GreetingBand: the eyebrow, the name, the
            lead and the one primary action. */}
        <GreetingBand part={part}>
          <p className="page-eyebrow text-night-soft" data-eyebrow="">
            {tp("eyebrow.home")}
          </p>
          <h1 className="mt-3 text-[2rem] leading-[1.08] text-ink [overflow-wrap:anywhere] sm:text-[2.75rem] sm:leading-[1.04]">
            {t(`greeting.${part}`, { name: me.user.display_name })}
          </h1>
          <p className="lead mt-3 max-w-[44ch] text-[1.0625rem] text-ink-soft sm:text-lg">
            {org ? t("orgLead", { org: org.org_name }) : t("orgLeadNoName")}
          </p>
          {setupNeeded ? (
            <div className="mt-6">
              <ButtonLink href="/settings/security" variant="primary">
                {t("turnOn")}
              </ButtonLink>
            </div>
          ) : org ? (
            <div className="mt-6">
              <ButtonLink href={inboxHref(memberships, org.org_id)} variant="primary">
                {(await getTranslations("orgHome"))("open")}
              </ButtonLink>
            </div>
          ) : null}
        </GreetingBand>
      </div>

      <div className="mt-8 flex max-w-5xl flex-col gap-12 lg:mt-10">
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
  const [t, ti, tt, ta, locale] = await Promise.all([
    getTranslations("orgHome"),
    getTranslations("inbox"),
    getTranslations("tracker"),
    getTranslations("activity"),
    getLocale(),
  ]);
  const [inboxRead, matchesRead, engagementsRead, briefsRead, activity] = await Promise.all([
    quietly(() => getInbox(org.org_id)),
    quietly(() => getMatches(org.org_id)),
    quietly(() => orgEngagements(org.org_id)),
    quietly(() => getBriefs(org.org_id)),
    getActivity(),
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
        {/* The figures count up once as the tiles come into view (CountUp; the real figure is read either way). */}
        <CountUp>
        <ul className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4 [&>li>*]:h-full">
          <li>
            <StatTile
              data-stat="inbox"
              label={t("stats.inbox")}
              value={stats.inbox === null ? unknown.value : stats.more ? t("stats.more", { count: stats.inbox }) : <CountFigure value={stats.inbox} />}
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
              value={stats.matches === null ? unknown.value : <CountFigure value={stats.matches} />}
              meta={stats.matches === null ? unknown.meta : stats.newestMatch ? t("stats.matchesMeta", { date: formatDay(locale, stats.newestMatch) }) : undefined}
              spark={matches && stats.matches !== null && stats.matches >= SPARK_FROM ? weeklySeries(matches.map((match) => match.created_at), now) : undefined}
              href={matchesHref(memberships, org.org_id)}
            />
          </li>
          <li>
            <StatTile
              data-stat="engagements"
              label={t("stats.engagements")}
              value={stats.engagements === null ? unknown.value : <CountFigure value={stats.engagements} />}
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
              value={briefs === null ? unknown.value : <CountFigure value={briefs.open} />}
              meta={
                briefs === null
                  ? unknown.meta
                  : briefs.inReview > 0
                    ? t("stats.briefsMetaReview", { count: briefs.inReview })
                    : briefs.open > 0
                      ? t("stats.briefsMetaProposals", { count: briefs.proposals })
                      : t("stats.briefsMetaNone")
              }
              href={problemsHref(memberships, org.org_id)}
            />
          </li>
        </ul>
        </CountUp>
      </section>

      {/* Your last 26 weeks (D-67): this person's own actions for the organisation, read as them; left out without an answer. */}
      {activity ? (
        <Section title={ta("title", { weeks: WEEKS })} headingId="home-activity" data-home="activity">
          <div className="rounded-panel border border-line bg-field p-4 sm:p-6">
            <ActivityCalendar activity={activity} />
          </div>
        </Section>
      ) : null}

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
          <ItemGrid>
            {inbox!.items.slice(0, INBOX_SHOWN).map((item) => (
              <li key={item.tag_id}>
                <InboxCard
                  item={item}
                  href={proposalHref(memberships, org.org_id, item.proposal.id)}
                  band={<NicheBand niche={item.proposal.teaser.niche?.slug} county={item.proposal.teaser.county_code} sizes={CARD_BAND} />}
                />
              </li>
            ))}
          </ItemGrid>
        ) : null}
      </Section>
    </>
  );
}
